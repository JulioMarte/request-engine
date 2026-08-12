import json
from collections import defaultdict
from datetime import datetime, timedelta
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.booking.adapters.db.reservation_commands import (
    _load_bookable_offering,
    _load_locked_profiles,
    _load_requirements,
    _lock_resource_ids,
    _lock_resources,
    _read_reservation,
    _revalidate_exact_slot,
    _reservation_from_json,
    _reservation_to_json,
    _validate_choice_cardinality,
    _validate_resource_capabilities,
    _validate_subject_location_and_origin,
)
from request_engine.modules.booking.adapters.db.resource_availability import (
    load_live_capacity_claims,
    load_resource_exceptions,
    load_resource_schedules,
)
from request_engine.modules.booking.application.commands.acquire_capacity_hold import (
    AcquireCapacityHoldCommand,
)
from request_engine.modules.booking.application.commands.confirm_capacity_hold import (
    ConfirmCapacityHoldCommand,
)
from request_engine.modules.booking.application.commands.reschedule_reservation import (
    RescheduleReservationCommand,
)
from request_engine.modules.booking.application.errors import (
    AppointmentUnavailable,
    BookingConfigurationError,
    CapacityHoldExpired,
    CapacityHoldNotActive,
    CapacityHoldNotFound,
    ReservationNotFound,
    ReservationNotReschedulable,
)
from request_engine.modules.booking.contracts.appointments import Reservation
from request_engine.modules.booking.contracts.holds import CapacityHold, CapacityHoldStatus
from request_engine.modules.booking.domain.availability import (
    ResourceAvailability,
    require_aware_utc,
)
from request_engine.modules.booking.domain.policy import slot_step_minutes
from request_engine.platform.audit.postgres import append_audit
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)
from request_engine.platform.outbox.postgres import append_outbox


class PostgresBookingCommitmentCommands:
    """Temporary capacity and reservation-replacement commands for V3 booking."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def acquire_capacity_hold(self, command: AcquireCapacityHoldCommand) -> CapacityHold:
        start_at = require_aware_utc(command.start_at, "start_at")
        expires_at = require_aware_utc(command.expires_at, "expires_at")
        fingerprint = command_fingerprint(
            "booking.acquire_capacity_hold",
            {
                "offering_version_id": command.offering_version_id,
                "subject_party_id": command.subject_party_id,
                "start_at": start_at,
                "expires_at": expires_at,
                "location_id": command.location_id,
                "resources": [
                    {
                        "requirement_id": str(choice.requirement_id),
                        "resource_id": str(choice.resource_id),
                    }
                    for choice in sorted(
                        command.resources,
                        key=lambda item: (str(item.requirement_id), str(item.resource_id)),
                    )
                ],
            },
        )

        async with tenant_transaction(self._session_factory, command.organization_id) as session:
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability="booking.acquire_capacity_hold",
                idempotency_key=command.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return _hold_from_json(cast(dict[str, object], replay["hold"]))

            now = cast(datetime, (await session.execute(text("SELECT clock_timestamp()"))).scalar_one())
            if expires_at <= now:
                raise CapacityHoldExpired(UUID(int=0))

            offering = await _load_bookable_offering(
                session,
                command.organization_id,
                command.offering_version_id,
            )
            duration_minutes = cast(int, offering["duration_minutes"])
            policy = cast(dict[str, object], offering["booking_policy"])
            step_minutes = slot_step_minutes(policy, duration_minutes)
            end_at = start_at + timedelta(minutes=duration_minutes)

            await _validate_subject_location_and_origin(
                session,
                organization_id=command.organization_id,
                subject_party_id=command.subject_party_id,
                location_id=command.location_id,
                origin_request_id=None,
            )
            requirements = await _load_requirements(
                session,
                command.organization_id,
                command.offering_version_id,
            )
            choices = _validate_choice_cardinality(requirements, command.resources)
            resources = await _lock_resources(
                session,
                organization_id=command.organization_id,
                resource_ids=tuple(choice.resource_id for choice in choices.values()),
            )
            await _validate_resource_capabilities(
                session,
                organization_id=command.organization_id,
                requirements=requirements,
                choices=choices,
                resources=resources,
                location_id=command.location_id,
            )
            profiles = await _load_locked_profiles(
                session,
                organization_id=command.organization_id,
                resources=resources,
                start_at=start_at,
                end_at=end_at,
            )
            _revalidate_exact_slot(
                requirements=requirements,
                choices=choices,
                profiles=profiles,
                start_at=start_at,
                end_at=end_at,
                duration_minutes=duration_minutes,
                step_minutes=step_minutes,
            )

            hold_id = cast(
                UUID,
                (
                    await session.execute(
                        text(
                            """
                            INSERT INTO request_engine.capacity_holds (
                                organization_id,
                                offering_version_id,
                                subject_party_id,
                                location_id,
                                during,
                                expires_at
                            ) VALUES (
                                :organization_id,
                                :offering_version_id,
                                :subject_party_id,
                                :location_id,
                                tstzrange(:start_at, :end_at, '[)'),
                                :expires_at
                            )
                            RETURNING id
                            """
                        ),
                        {
                            "organization_id": command.organization_id,
                            "offering_version_id": command.offering_version_id,
                            "subject_party_id": command.subject_party_id,
                            "location_id": command.location_id,
                            "start_at": start_at,
                            "end_at": end_at,
                            "expires_at": expires_at,
                        },
                    )
                ).scalar_one(),
            )
            for requirement in sorted(requirements.values(), key=lambda item: item.ordinal):
                choice = choices[requirement.id]
                await session.execute(
                    text(
                        """
                        INSERT INTO request_engine.capacity_claims (
                            organization_id,
                            resource_id,
                            requirement_id,
                            hold_id,
                            during,
                            quantity
                        ) VALUES (
                            :organization_id,
                            :resource_id,
                            :requirement_id,
                            :hold_id,
                            tstzrange(:start_at, :end_at, '[)'),
                            :quantity
                        )
                        """
                    ),
                    {
                        "organization_id": command.organization_id,
                        "resource_id": choice.resource_id,
                        "requirement_id": requirement.id,
                        "hold_id": hold_id,
                        "start_at": start_at,
                        "end_at": end_at,
                        "quantity": requirement.quantity,
                    },
                )

            await append_audit(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                command_name="booking.acquire_capacity_hold",
                aggregate_kind="CapacityHold",
                aggregate_id=hold_id,
                idempotency_id=idempotency_id,
                details={
                    "offering_version_id": str(command.offering_version_id),
                    "subject_party_id": str(command.subject_party_id),
                    "start_at": start_at.isoformat(),
                    "end_at": end_at.isoformat(),
                    "expires_at": expires_at.isoformat(),
                },
            )
            await append_outbox(
                session,
                organization_id=command.organization_id,
                event_type="capacity_hold.acquired.v1",
                aggregate_kind="CapacityHold",
                aggregate_id=hold_id,
                payload={
                    "hold_id": str(hold_id),
                    "start_at": start_at.isoformat(),
                    "end_at": end_at.isoformat(),
                    "expires_at": expires_at.isoformat(),
                },
            )
            hold = await _read_hold(session, command.organization_id, hold_id)
            await complete_idempotency(
                session,
                idempotency_id,
                {"hold": _hold_to_json(hold)},
            )
            return hold

    async def confirm_capacity_hold(self, command: ConfirmCapacityHoldCommand) -> Reservation:
        fingerprint = command_fingerprint(
            "booking.confirm_capacity_hold",
            {"hold_id": command.hold_id, "origin_request_id": command.origin_request_id},
        )
        async with tenant_transaction(self._session_factory, command.organization_id) as session:
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability="booking.confirm_capacity_hold",
                idempotency_key=command.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return _reservation_from_json(cast(dict[str, object], replay["reservation"]))

            hold_row = await _lock_hold(session, command.organization_id, command.hold_id)
            _assert_live_hold(hold_row, command.hold_id)
            await _validate_subject_location_and_origin(
                session,
                organization_id=command.organization_id,
                subject_party_id=cast(UUID, hold_row["subject_party_id"]),
                location_id=cast(UUID | None, hold_row["location_id"]),
                origin_request_id=command.origin_request_id,
            )
            resource_ids = await _active_owner_resource_ids(
                session,
                command.organization_id,
                hold_id=command.hold_id,
            )
            await _lock_resource_ids(session, command.organization_id, resource_ids)
            hold_row = await _read_locked_hold(session, command.organization_id, command.hold_id)
            _assert_live_hold(hold_row, command.hold_id)

            offering = await _load_bookable_offering(
                session,
                command.organization_id,
                cast(UUID, hold_row["offering_version_id"]),
            )
            policy = cast(dict[str, object], offering["booking_policy"])
            reservation_id = cast(
                UUID,
                (
                    await session.execute(
                        text(
                            """
                            INSERT INTO request_engine.reservations (
                                organization_id,
                                offering_version_id,
                                subject_party_id,
                                location_id,
                                origin_request_id,
                                during,
                                booking_policy_snapshot
                            ) VALUES (
                                :organization_id,
                                :offering_version_id,
                                :subject_party_id,
                                :location_id,
                                :origin_request_id,
                                :during,
                                CAST(:booking_policy AS jsonb)
                            )
                            RETURNING id
                            """
                        ),
                        {
                            "organization_id": command.organization_id,
                            "offering_version_id": hold_row["offering_version_id"],
                            "subject_party_id": hold_row["subject_party_id"],
                            "location_id": hold_row["location_id"],
                            "origin_request_id": command.origin_request_id,
                            "during": hold_row["during"],
                            "booking_policy": json.dumps(policy, separators=(",", ":")),
                        },
                    )
                ).scalar_one(),
            )
            await session.execute(
                text(
                    """
                    UPDATE request_engine.capacity_claims
                    SET reservation_id = :reservation_id,
                        updated_at = clock_timestamp()
                    WHERE organization_id = :organization_id
                      AND hold_id = :hold_id
                      AND reservation_id IS NULL
                      AND status = 'active'
                    """
                ),
                {
                    "organization_id": command.organization_id,
                    "hold_id": command.hold_id,
                    "reservation_id": reservation_id,
                },
            )
            await session.execute(
                text(
                    """
                    UPDATE request_engine.capacity_holds
                    SET status = 'consumed',
                        revision = revision + 1,
                        updated_at = clock_timestamp()
                    WHERE organization_id = :organization_id
                      AND id = :hold_id
                    """
                ),
                {"organization_id": command.organization_id, "hold_id": command.hold_id},
            )

            await append_audit(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                command_name="booking.confirm_capacity_hold",
                aggregate_kind="Reservation",
                aggregate_id=reservation_id,
                idempotency_id=idempotency_id,
                details={"hold_id": str(command.hold_id)},
            )
            await append_outbox(
                session,
                organization_id=command.organization_id,
                event_type="reservation.created.v1",
                aggregate_kind="Reservation",
                aggregate_id=reservation_id,
                payload={
                    "reservation_id": str(reservation_id),
                    "hold_id": str(command.hold_id),
                    "subject_party_id": str(hold_row["subject_party_id"]),
                    "start_at": cast(datetime, hold_row["start_at"]).isoformat(),
                    "end_at": cast(datetime, hold_row["end_at"]).isoformat(),
                },
            )
            reservation = await _read_reservation(
                session,
                command.organization_id,
                reservation_id,
            )
            await complete_idempotency(
                session,
                idempotency_id,
                {"reservation": _reservation_to_json(reservation)},
            )
            return reservation

    async def reschedule_reservation(self, command: RescheduleReservationCommand) -> Reservation:
        start_at = require_aware_utc(command.start_at, "start_at")
        fingerprint = command_fingerprint(
            "booking.reschedule_reservation",
            {
                "reservation_id": command.reservation_id,
                "start_at": start_at,
                "location_id": command.location_id,
                "resources": [
                    {
                        "requirement_id": str(choice.requirement_id),
                        "resource_id": str(choice.resource_id),
                    }
                    for choice in sorted(
                        command.resources,
                        key=lambda item: (str(item.requirement_id), str(item.resource_id)),
                    )
                ],
            },
        )
        async with tenant_transaction(self._session_factory, command.organization_id) as session:
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability="booking.reschedule_reservation",
                idempotency_key=command.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return _reservation_from_json(cast(dict[str, object], replay["reservation"]))

            reservation_row = await _lock_reservation(
                session,
                command.organization_id,
                command.reservation_id,
            )
            status = cast(str, reservation_row["status"])
            if status != "confirmed":
                raise ReservationNotReschedulable(command.reservation_id, status)

            offering_version_id = cast(UUID, reservation_row["offering_version_id"])
            offering = await _load_bookable_offering(
                session,
                command.organization_id,
                offering_version_id,
            )
            duration_minutes = cast(int, offering["duration_minutes"])
            policy = cast(dict[str, object], reservation_row["booking_policy_snapshot"])
            step_minutes = slot_step_minutes(policy, duration_minutes)
            end_at = start_at + timedelta(minutes=duration_minutes)

            await _validate_subject_location_and_origin(
                session,
                organization_id=command.organization_id,
                subject_party_id=cast(UUID, reservation_row["subject_party_id"]),
                location_id=command.location_id,
                origin_request_id=cast(UUID | None, reservation_row["origin_request_id"]),
            )
            requirements = await _load_requirements(
                session,
                command.organization_id,
                offering_version_id,
            )
            choices = _validate_choice_cardinality(requirements, command.resources)
            old_claims = await _active_reservation_claims(
                session,
                command.organization_id,
                command.reservation_id,
            )
            old_resource_ids = tuple(cast(UUID, row["resource_id"]) for row in old_claims)
            new_resource_ids = tuple(choice.resource_id for choice in choices.values())
            union_resource_ids = tuple(sorted(set(old_resource_ids + new_resource_ids), key=str))
            resources = await _lock_resources(
                session,
                organization_id=command.organization_id,
                resource_ids=union_resource_ids,
            )
            selected_resources = {
                resource_id: resources[resource_id] for resource_id in set(new_resource_ids)
            }
            await _validate_resource_capabilities(
                session,
                organization_id=command.organization_id,
                requirements=requirements,
                choices=choices,
                resources=selected_resources,
                location_id=command.location_id,
            )
            profiles = await _load_profiles_excluding_reservation(
                session,
                organization_id=command.organization_id,
                resources=selected_resources,
                start_at=start_at,
                end_at=end_at,
                reservation_id=command.reservation_id,
            )
            _revalidate_exact_slot(
                requirements=requirements,
                choices=choices,
                profiles=profiles,
                start_at=start_at,
                end_at=end_at,
                duration_minutes=duration_minutes,
                step_minutes=step_minutes,
            )

            await session.execute(
                text(
                    """
                    UPDATE request_engine.capacity_claims
                    SET status = 'released',
                        released_at = clock_timestamp(),
                        updated_at = clock_timestamp()
                    WHERE organization_id = :organization_id
                      AND reservation_id = :reservation_id
                      AND status = 'active'
                    """
                ),
                {
                    "organization_id": command.organization_id,
                    "reservation_id": command.reservation_id,
                },
            )
            await session.execute(
                text(
                    """
                    UPDATE request_engine.reservations
                    SET location_id = :location_id,
                        during = tstzrange(:start_at, :end_at, '[)'),
                        revision = revision + 1,
                        updated_at = clock_timestamp()
                    WHERE organization_id = :organization_id
                      AND id = :reservation_id
                    """
                ),
                {
                    "organization_id": command.organization_id,
                    "reservation_id": command.reservation_id,
                    "location_id": command.location_id,
                    "start_at": start_at,
                    "end_at": end_at,
                },
            )

            old_by_requirement = {
                cast(UUID, row["requirement_id"]): cast(UUID, row["id"]) for row in old_claims
            }
            replacement_ids: dict[UUID, UUID] = {}
            for requirement in sorted(requirements.values(), key=lambda item: item.ordinal):
                choice = choices[requirement.id]
                new_claim_id = cast(
                    UUID,
                    (
                        await session.execute(
                            text(
                                """
                                INSERT INTO request_engine.capacity_claims (
                                    organization_id,
                                    resource_id,
                                    requirement_id,
                                    reservation_id,
                                    during,
                                    quantity
                                ) VALUES (
                                    :organization_id,
                                    :resource_id,
                                    :requirement_id,
                                    :reservation_id,
                                    tstzrange(:start_at, :end_at, '[)'),
                                    :quantity
                                )
                                RETURNING id
                                """
                            ),
                            {
                                "organization_id": command.organization_id,
                                "resource_id": choice.resource_id,
                                "requirement_id": requirement.id,
                                "reservation_id": command.reservation_id,
                                "start_at": start_at,
                                "end_at": end_at,
                                "quantity": requirement.quantity,
                            },
                        )
                    ).scalar_one(),
                )
                replacement_ids[requirement.id] = new_claim_id

            for requirement_id, old_claim_id in old_by_requirement.items():
                await session.execute(
                    text(
                        """
                        UPDATE request_engine.capacity_claims
                        SET status = 'replaced',
                            replaced_by_claim_id = :new_claim_id,
                            updated_at = clock_timestamp()
                        WHERE organization_id = :organization_id
                          AND id = :old_claim_id
                          AND status = 'released'
                        """
                    ),
                    {
                        "organization_id": command.organization_id,
                        "old_claim_id": old_claim_id,
                        "new_claim_id": replacement_ids[requirement_id],
                    },
                )

            await append_audit(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                command_name="booking.reschedule_reservation",
                aggregate_kind="Reservation",
                aggregate_id=command.reservation_id,
                idempotency_id=idempotency_id,
                details={
                    "old_start_at": cast(datetime, reservation_row["start_at"]).isoformat(),
                    "old_end_at": cast(datetime, reservation_row["end_at"]).isoformat(),
                    "new_start_at": start_at.isoformat(),
                    "new_end_at": end_at.isoformat(),
                },
            )
            await append_outbox(
                session,
                organization_id=command.organization_id,
                event_type="reservation.rescheduled.v1",
                aggregate_kind="Reservation",
                aggregate_id=command.reservation_id,
                payload={
                    "reservation_id": str(command.reservation_id),
                    "start_at": start_at.isoformat(),
                    "end_at": end_at.isoformat(),
                },
            )
            reservation = await _read_reservation(
                session,
                command.organization_id,
                command.reservation_id,
            )
            await complete_idempotency(
                session,
                idempotency_id,
                {"reservation": _reservation_to_json(reservation)},
            )
            return reservation


async def _lock_hold(
    session: AsyncSession,
    organization_id: UUID,
    hold_id: UUID,
) -> RowMapping:
    row = await _read_hold_row(session, organization_id, hold_id, lock=True)
    if row is None:
        raise CapacityHoldNotFound(hold_id)
    return row


async def _read_locked_hold(
    session: AsyncSession,
    organization_id: UUID,
    hold_id: UUID,
) -> RowMapping:
    row = await _read_hold_row(session, organization_id, hold_id, lock=False)
    if row is None:
        raise CapacityHoldNotFound(hold_id)
    return row


async def _read_hold_row(
    session: AsyncSession,
    organization_id: UUID,
    hold_id: UUID,
    *,
    lock: bool,
) -> RowMapping | None:
    suffix = " FOR UPDATE" if lock else ""
    query = text(
        """
        SELECT id, offering_version_id, subject_party_id, location_id,
               during, lower(during) AS start_at, upper(during) AS end_at,
               status, expires_at, revision
        FROM request_engine.capacity_holds
        WHERE organization_id = :organization_id
          AND id = :hold_id
        """
        + suffix
    )
    return (
        (
            await session.execute(
                query,
                {"organization_id": organization_id, "hold_id": hold_id},
            )
        )
        .mappings()
        .first()
    )


def _assert_live_hold(row: RowMapping, hold_id: UUID) -> None:
    status = cast(str, row["status"])
    if status != "active":
        raise CapacityHoldNotActive(hold_id, status)
    if cast(datetime, row["expires_at"]) <= datetime.now().astimezone():
        raise CapacityHoldExpired(hold_id)


async def _active_owner_resource_ids(
    session: AsyncSession,
    organization_id: UUID,
    *,
    hold_id: UUID,
) -> tuple[UUID, ...]:
    rows = (
        await session.execute(
            text(
                """
                SELECT DISTINCT resource_id
                FROM request_engine.capacity_claims
                WHERE organization_id = :organization_id
                  AND hold_id = :hold_id
                  AND reservation_id IS NULL
                  AND status = 'active'
                ORDER BY resource_id
                """
            ),
            {"organization_id": organization_id, "hold_id": hold_id},
        )
    ).all()
    resource_ids = tuple(cast(UUID, row[0]) for row in rows)
    if not resource_ids:
        raise BookingConfigurationError(f"CapacityHold {hold_id} has no active claims")
    return resource_ids


async def _lock_reservation(
    session: AsyncSession,
    organization_id: UUID,
    reservation_id: UUID,
) -> RowMapping:
    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT id, offering_version_id, subject_party_id, location_id,
                           origin_request_id, during,
                           lower(during) AS start_at, upper(during) AS end_at,
                           status, booking_policy_snapshot, revision
                    FROM request_engine.reservations
                    WHERE organization_id = :organization_id
                      AND id = :reservation_id
                    FOR UPDATE
                    """
                ),
                {
                    "organization_id": organization_id,
                    "reservation_id": reservation_id,
                },
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise ReservationNotFound(reservation_id)
    return row


async def _active_reservation_claims(
    session: AsyncSession,
    organization_id: UUID,
    reservation_id: UUID,
) -> tuple[RowMapping, ...]:
    rows = (
        (
            await session.execute(
                text(
                    """
                    SELECT id, resource_id, requirement_id, quantity,
                           lower(during) AS start_at, upper(during) AS end_at
                    FROM request_engine.capacity_claims
                    WHERE organization_id = :organization_id
                      AND reservation_id = :reservation_id
                      AND status = 'active'
                    ORDER BY requirement_id
                    """
                ),
                {
                    "organization_id": organization_id,
                    "reservation_id": reservation_id,
                },
            )
        )
        .mappings()
        .all()
    )
    if not rows:
        raise BookingConfigurationError(f"Reservation {reservation_id} has no active claims")
    return tuple(rows)


async def _load_profiles_excluding_reservation(
    session: AsyncSession,
    *,
    organization_id: UUID,
    resources: dict[UUID, object],
    start_at: datetime,
    end_at: datetime,
    reservation_id: UUID,
) -> dict[UUID, ResourceAvailability]:
    resource_ids = tuple(sorted(resources, key=str))
    schedules = await load_resource_schedules(session, organization_id, resource_ids)
    exceptions = await load_resource_exceptions(
        session,
        organization_id,
        resource_ids,
        start_at,
        end_at,
    )
    claims = await load_live_capacity_claims(
        session,
        organization_id,
        resource_ids,
        start_at,
        end_at,
        exclude_reservation_id=reservation_id,
    )
    profiles: dict[UUID, ResourceAvailability] = {}
    for resource_id, resource in resources.items():
        capacity_model = getattr(resource, "capacity_model")
        capacity_units = getattr(resource, "capacity_units")
        default_timezone = getattr(resource, "default_timezone")
        profiles[resource_id] = ResourceAvailability(
            capacity_model=capacity_model,
            capacity_units=capacity_units,
            default_timezone=default_timezone,
            schedules=schedules.get(resource_id, ()),
            exceptions=exceptions.get(resource_id, ()),
            live_claims=claims.get(resource_id, ()),
        )
    return profiles


async def _read_hold(
    session: AsyncSession,
    organization_id: UUID,
    hold_id: UUID,
) -> CapacityHold:
    row = await _read_hold_row(session, organization_id, hold_id, lock=False)
    if row is None:
        raise CapacityHoldNotFound(hold_id)
    return _hold_from_row(row)


def _hold_from_row(row: RowMapping) -> CapacityHold:
    return CapacityHold(
        id=cast(UUID, row["id"]),
        offering_version_id=cast(UUID, row["offering_version_id"]),
        subject_party_id=cast(UUID, row["subject_party_id"]),
        location_id=cast(UUID | None, row["location_id"]),
        start_at=cast(datetime, row["start_at"]),
        end_at=cast(datetime, row["end_at"]),
        expires_at=cast(datetime, row["expires_at"]),
        status=CapacityHoldStatus(cast(str, row["status"])),
        revision=cast(int, row["revision"]),
    )


def _hold_to_json(hold: CapacityHold) -> dict[str, object]:
    return {
        "id": str(hold.id),
        "offering_version_id": str(hold.offering_version_id),
        "subject_party_id": str(hold.subject_party_id),
        "location_id": str(hold.location_id) if hold.location_id else None,
        "start_at": hold.start_at.isoformat(),
        "end_at": hold.end_at.isoformat(),
        "expires_at": hold.expires_at.isoformat(),
        "status": hold.status.value,
        "revision": hold.revision,
    }


def _hold_from_json(data: dict[str, object]) -> CapacityHold:
    location_raw = cast(str | None, data["location_id"])
    return CapacityHold(
        id=UUID(cast(str, data["id"])),
        offering_version_id=UUID(cast(str, data["offering_version_id"])),
        subject_party_id=UUID(cast(str, data["subject_party_id"])),
        location_id=UUID(location_raw) if location_raw else None,
        start_at=datetime.fromisoformat(cast(str, data["start_at"])),
        end_at=datetime.fromisoformat(cast(str, data["end_at"])),
        expires_at=datetime.fromisoformat(cast(str, data["expires_at"])),
        status=CapacityHoldStatus(cast(str, data["status"])),
        revision=cast(int, data["revision"]),
    )
