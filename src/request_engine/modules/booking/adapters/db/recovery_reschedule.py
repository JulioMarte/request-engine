from datetime import datetime, timedelta
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.booking.adapters.db.capacity_errors import (
    normalize_capacity_integrity_error,
)
from request_engine.modules.booking.adapters.db.commitment_commands import (
    _active_reservation_claims,
    _load_profiles_excluding_reservation,
    _lock_reservation,
)
from request_engine.modules.booking.adapters.db.reservation_commands import (
    ensure_reservation_revision,
    load_bookable_offering,
    load_requirements,
    lock_resources,
    read_reservation,
    reservation_from_json,
    reservation_to_json,
    revalidate_exact_slot,
    validate_choice_cardinality,
    validate_resource_capabilities,
    validate_subject_location_and_origin,
)
from request_engine.modules.booking.adapters.db.subject_authority import require_subject_authority
from request_engine.modules.booking.application.authority import MANAGE_APPOINTMENT_SCOPE
from request_engine.modules.booking.application.errors import (
    AppointmentUnavailable,
    InvalidResourceSelection,
    OfferingVersionNotBookable,
    OfferingVersionNotFound,
    ReservationNotReschedulable,
    ReservationRevisionConflict,
)
from request_engine.modules.booking.contracts.appointments import Reservation
from request_engine.modules.booking.contracts.recovery import (
    RecoveryBookingConflict,
    RecoveryRescheduleRequest,
    RecoveryTargetUnavailable,
)
from request_engine.modules.booking.domain.availability import require_aware_utc
from request_engine.modules.booking.domain.policy import slot_step_minutes
from request_engine.platform.audit.postgres import append_audit
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)
from request_engine.platform.outbox.postgres import append_outbox


class PostgresGuardedRecoveryReschedule:
    """Booking-owned F5 reschedule with atomic source-revision guards."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def reschedule(self, request: RecoveryRescheduleRequest) -> Reservation:
        try:
            return await self._reschedule(request)
        except IntegrityError as exc:
            normalize_capacity_integrity_error(exc)
        except ReservationRevisionConflict as exc:
            raise RecoveryBookingConflict(str(exc)) from exc
        except ReservationNotReschedulable as exc:
            raise RecoveryBookingConflict(str(exc)) from exc
        except (AppointmentUnavailable, InvalidResourceSelection) as exc:
            raise RecoveryTargetUnavailable(str(exc)) from exc
        except (OfferingVersionNotFound, OfferingVersionNotBookable) as exc:
            raise RecoveryTargetUnavailable(str(exc)) from exc

    async def _reschedule(self, request: RecoveryRescheduleRequest) -> Reservation:
        if any(choice.resource_location_assignment_id is not None for choice in request.resources):
            raise RecoveryTargetUnavailable("contextual recovery reschedule is not supported")
        start_at = require_aware_utc(request.start_at, "start_at")
        fingerprint = command_fingerprint(
            "booking.reschedule_reservation.recovery.v1",
            {
                "reservation_id": request.reservation_id,
                "expected_revision": request.expected_revision,
                "start_at": start_at,
                "location_id": request.location_id,
                "source_resource_id": request.source_resource_id,
                "expected_source_resource_availability_revision": (
                    request.expected_source_resource_availability_revision
                ),
                "source_location_id": request.source_location_id,
                "expected_source_location_operational_revision": (
                    request.expected_source_location_operational_revision
                ),
                "resources": [
                    {
                        "requirement_id": str(choice.requirement_id),
                        "resource_id": str(choice.resource_id),
                    }
                    for choice in sorted(
                        request.resources,
                        key=lambda item: (str(item.requirement_id), str(item.resource_id)),
                    )
                ],
            },
        )
        async with tenant_transaction(self._session_factory, request.organization_id) as session:
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=request.organization_id,
                principal_id=request.principal_id,
                capability="booking.reschedule_reservation",
                idempotency_key=request.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return reservation_from_json(cast(dict[str, object], replay["reservation"]))

            reservation_row = await _lock_reservation(
                session,
                request.organization_id,
                request.reservation_id,
            )
            subject_party_id = cast(UUID, reservation_row["subject_party_id"])
            authority = await require_subject_authority(
                session,
                organization_id=request.organization_id,
                principal_id=request.principal_id,
                subject_party_id=subject_party_id,
                scope_key=MANAGE_APPOINTMENT_SCOPE,
                allow_operator_override=request.allow_subject_override,
            )
            try:
                ensure_reservation_revision(
                    reservation_row,
                    request.reservation_id,
                    request.expected_revision,
                )
            except ReservationRevisionConflict:
                raise
            status = cast(str, reservation_row["status"])
            if status != "confirmed":
                raise ReservationNotReschedulable(request.reservation_id, status)

            await _lock_recovery_locations(
                session,
                organization_id=request.organization_id,
                source_location_id=request.source_location_id,
                expected_source_revision=request.expected_source_location_operational_revision,
                target_location_id=request.location_id,
            )

            offering_version_id = cast(UUID, reservation_row["offering_version_id"])
            offering = await load_bookable_offering(
                session,
                request.organization_id,
                offering_version_id,
            )
            duration_minutes = cast(int, offering["duration_minutes"])
            policy = cast(dict[str, object], reservation_row["booking_policy_snapshot"])
            step_minutes = slot_step_minutes(policy, duration_minutes)
            end_at = start_at + timedelta(minutes=duration_minutes)

            await validate_subject_location_and_origin(
                session,
                organization_id=request.organization_id,
                subject_party_id=subject_party_id,
                location_id=request.location_id,
                origin_request_id=cast(UUID | None, reservation_row["origin_request_id"]),
            )
            requirements = await load_requirements(
                session,
                request.organization_id,
                offering_version_id,
            )
            choices = validate_choice_cardinality(requirements, request.resources)
            old_claims = await _active_reservation_claims(
                session,
                request.organization_id,
                request.reservation_id,
            )
            old_resource_ids = tuple(cast(UUID, row["resource_id"]) for row in old_claims)
            if request.source_resource_id not in old_resource_ids:
                raise RecoveryBookingConflict(
                    "recovery source Resource is no longer an active Reservation commitment"
                )
            new_resource_ids = tuple(choice.resource_id for choice in choices.values())
            union_resource_ids = tuple(sorted(set(old_resource_ids + new_resource_ids), key=str))
            resources = await lock_resources(
                session,
                organization_id=request.organization_id,
                resource_ids=union_resource_ids,
            )
            await _require_source_resource_revision(
                session,
                organization_id=request.organization_id,
                resource_id=request.source_resource_id,
                expected_revision=request.expected_source_resource_availability_revision,
            )
            selected_resources = {
                resource_id: resources[resource_id] for resource_id in set(new_resource_ids)
            }
            await validate_resource_capabilities(
                session,
                organization_id=request.organization_id,
                requirements=requirements,
                choices=choices,
                resources=selected_resources,
                location_id=request.location_id,
            )
            profiles = await _load_profiles_excluding_reservation(
                session,
                organization_id=request.organization_id,
                resources=selected_resources,
                start_at=start_at,
                end_at=end_at,
                reservation_id=request.reservation_id,
            )
            revalidate_exact_slot(
                requirements=requirements,
                choices=choices,
                profiles=profiles,
                start_at=start_at,
                end_at=end_at,
                duration_minutes=duration_minutes,
                step_minutes=step_minutes,
            )

            await _replace_reservation_commitment(
                session,
                request=request,
                requirements=requirements,
                choices=choices,
                old_claims=old_claims,
                start_at=start_at,
                end_at=end_at,
            )
            old_location_id = cast(UUID | None, reservation_row["location_id"])
            old_start_at = cast(datetime, reservation_row["start_at"])
            old_end_at = cast(datetime, reservation_row["end_at"])
            await append_audit(
                session,
                organization_id=request.organization_id,
                principal_id=request.principal_id,
                command_name="booking.reschedule_reservation",
                aggregate_kind="Reservation",
                aggregate_id=request.reservation_id,
                idempotency_id=idempotency_id,
                details={
                    "subject_party_id": str(subject_party_id),
                    "subject_authority": authority.audit_details(),
                    "expected_revision": request.expected_revision,
                    "recovery_guarded": True,
                    "source_resource_id": str(request.source_resource_id),
                    "source_resource_availability_revision": (
                        request.expected_source_resource_availability_revision
                    ),
                    "source_location_id": str(request.source_location_id),
                    "source_location_operational_revision": (
                        request.expected_source_location_operational_revision
                    ),
                    "old_location_id": str(old_location_id) if old_location_id else None,
                    "new_location_id": str(request.location_id) if request.location_id else None,
                    "old_start_at": old_start_at.isoformat(),
                    "old_end_at": old_end_at.isoformat(),
                    "new_start_at": start_at.isoformat(),
                    "new_end_at": end_at.isoformat(),
                },
            )
            await append_outbox(
                session,
                organization_id=request.organization_id,
                event_type="reservation.rescheduled.v1",
                aggregate_kind="Reservation",
                aggregate_id=request.reservation_id,
                payload={
                    "reservation_id": str(request.reservation_id),
                    "old_location_id": str(old_location_id) if old_location_id else None,
                    "old_start_at": old_start_at.isoformat(),
                    "old_end_at": old_end_at.isoformat(),
                    "start_at": start_at.isoformat(),
                    "end_at": end_at.isoformat(),
                    "recovery_guarded": True,
                },
            )
            reservation = await read_reservation(
                session,
                request.organization_id,
                request.reservation_id,
            )
            await complete_idempotency(
                session,
                idempotency_id,
                {"reservation": reservation_to_json(reservation)},
            )
            return reservation


async def _lock_recovery_locations(
    session: AsyncSession,
    *,
    organization_id: UUID,
    source_location_id: UUID,
    expected_source_revision: int,
    target_location_id: UUID | None,
) -> None:
    location_ids = tuple(
        sorted(
            {source_location_id} | ({target_location_id} if target_location_id is not None else set()),
            key=str,
        )
    )
    rows = (
        (
            await session.execute(
                text(
                    """
                    SELECT id, active, operational_revision
                    FROM request_engine.locations
                    WHERE organization_id = :organization_id
                      AND id = ANY(CAST(:location_ids AS uuid[]))
                    ORDER BY id
                    FOR UPDATE
                    """
                ),
                {
                    "organization_id": organization_id,
                    "location_ids": [str(value) for value in location_ids],
                },
            )
        )
        .mappings()
        .all()
    )
    if len(rows) != len(location_ids):
        raise RecoveryBookingConflict("recovery Location provenance no longer exists")
    by_id = {cast(UUID, row["id"]): row for row in rows}
    source = by_id[source_location_id]
    if cast(int, source["operational_revision"]) != expected_source_revision:
        raise RecoveryBookingConflict("recovery source Location revision changed")
    if any(row["active"] is not True for row in rows):
        raise RecoveryTargetUnavailable("recovery source or target Location is inactive")


async def _require_source_resource_revision(
    session: AsyncSession,
    *,
    organization_id: UUID,
    resource_id: UUID,
    expected_revision: int,
) -> None:
    current = cast(
        int,
        (
            await session.execute(
                text(
                    """
                    SELECT availability_revision
                    FROM request_engine.resources
                    WHERE organization_id = :organization_id
                      AND id = :resource_id
                    """
                ),
                {"organization_id": organization_id, "resource_id": resource_id},
            )
        ).scalar_one(),
    )
    if current != expected_revision:
        raise RecoveryBookingConflict("recovery source Resource revision changed")


async def _replace_reservation_commitment(
    session: AsyncSession,
    *,
    request: RecoveryRescheduleRequest,
    requirements: dict[UUID, object],
    choices: dict[UUID, object],
    old_claims: tuple[object, ...],
    start_at: datetime,
    end_at: datetime,
) -> None:
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
            "organization_id": request.organization_id,
            "reservation_id": request.reservation_id,
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
            "organization_id": request.organization_id,
            "reservation_id": request.reservation_id,
            "location_id": request.location_id,
            "start_at": start_at,
            "end_at": end_at,
        },
    )
    old_by_requirement = {
        cast(UUID, row["requirement_id"]): cast(UUID, row["id"])
        for row in cast(tuple[dict[str, object], ...], old_claims)
    }
    if set(old_by_requirement) != set(requirements):
        raise RuntimeError("Reservation no longer has the canonical claim set")
    replacement_ids: dict[UUID, UUID] = {}
    for requirement_id, requirement in requirements.items():
        choice = cast(object, choices[requirement_id])
        resource_id = cast(UUID, getattr(choice, "resource_id"))
        quantity = cast(int, getattr(requirement, "quantity"))
        new_claim_id = cast(
            UUID,
            (
                await session.execute(
                    text(
                        """
                        INSERT INTO request_engine.capacity_claims (
                            organization_id, resource_id, requirement_id,
                            reservation_id, during, quantity
                        ) VALUES (
                            :organization_id, :resource_id, :requirement_id,
                            :reservation_id, tstzrange(:start_at, :end_at, '[)'), :quantity
                        )
                        RETURNING id
                        """
                    ),
                    {
                        "organization_id": request.organization_id,
                        "resource_id": resource_id,
                        "requirement_id": requirement_id,
                        "reservation_id": request.reservation_id,
                        "start_at": start_at,
                        "end_at": end_at,
                        "quantity": quantity,
                    },
                )
            ).scalar_one(),
        )
        replacement_ids[requirement_id] = new_claim_id
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
                "organization_id": request.organization_id,
                "old_claim_id": old_claim_id,
                "new_claim_id": replacement_ids[requirement_id],
            },
        )
