from collections import defaultdict
from dataclasses import dataclass
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.booking.adapters.db.effective_booking_policy import (
    EFFECTIVE_BOOKING_POLICY_SELECT,
)
from request_engine.modules.booking.adapters.db.reservation_reader import reservation_from_row
from request_engine.modules.booking.adapters.db.subject_authority import require_subject_authority
from request_engine.modules.booking.application.authority import MANAGE_APPOINTMENT_SCOPE
from request_engine.modules.booking.application.commands.cancel_reservation import (
    CancelReservationCommand,
)
from request_engine.modules.booking.application.errors import (
    AppointmentUnavailable,
    BookingConfigurationError,
    InvalidResourceSelection,
    OfferingVersionNotBookable,
    OfferingVersionNotFound,
    ReservationNotCancellable,
    ReservationNotFound,
    ReservationRevisionConflict,
)
from request_engine.modules.booking.contracts.appointments import Reservation, ResourceChoice
from request_engine.modules.booking.domain.availability import (
    CapacityModel,
    ResourceAvailability,
    find_resource_intervals,
    interval_has_resource_capacity,
)
from request_engine.platform.audit.postgres import append_audit
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)
from request_engine.platform.outbox.postgres import append_outbox


@dataclass(frozen=True, slots=True)
class _Requirement:
    id: UUID
    ordinal: int
    capability_id: UUID
    quantity: int


@dataclass(frozen=True, slots=True)
class LockedResource:
    id: UUID
    capacity_model: CapacityModel
    capacity_units: int


class PostgresReservationCommands:
    """Reservation lifecycle mutations shared by the contextual booking surface."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def cancel_reservation(self, command: CancelReservationCommand) -> Reservation:
        fingerprint = command_fingerprint(
            "booking.cancel_reservation",
            {
                "reservation_id": command.reservation_id,
                "expected_revision": command.expected_revision,
                "reason": command.reason,
            },
        )
        async with tenant_transaction(self._session_factory, command.organization_id) as session:
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability="booking.cancel_reservation",
                idempotency_key=command.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return reservation_from_json(cast(dict[str, object], replay["reservation"]))

            locked = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT id, status, subject_party_id, revision
                            FROM request_engine.reservations
                            WHERE organization_id = :organization_id
                              AND id = :reservation_id
                            FOR UPDATE
                            """
                        ),
                        {
                            "organization_id": command.organization_id,
                            "reservation_id": command.reservation_id,
                        },
                    )
                )
                .mappings()
                .first()
            )
            if locked is None:
                raise ReservationNotFound(command.reservation_id)
            subject_party_id = cast(UUID, locked["subject_party_id"])
            authority = await require_subject_authority(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                subject_party_id=subject_party_id,
                scope_key=MANAGE_APPOINTMENT_SCOPE,
                allow_operator_override=command.allow_subject_override,
            )
            ensure_reservation_revision(locked, command.reservation_id, command.expected_revision)
            status = cast(str, locked["status"])
            if status != "confirmed":
                raise ReservationNotCancellable(command.reservation_id, status)

            resource_rows = (
                await session.execute(
                    text(
                        """
                        SELECT DISTINCT resource_id
                        FROM request_engine.capacity_claims
                        WHERE organization_id = :organization_id
                          AND reservation_id = :reservation_id
                          AND status = 'active'
                        ORDER BY resource_id
                        """
                    ),
                    {
                        "organization_id": command.organization_id,
                        "reservation_id": command.reservation_id,
                    },
                )
            ).all()
            resource_ids = tuple(cast(UUID, row[0]) for row in resource_rows)
            if not resource_ids:
                raise BookingConfigurationError(
                    f"confirmed Reservation {command.reservation_id} has no active claims"
                )
            await lock_resource_ids(session, command.organization_id, resource_ids)

            await session.execute(
                text(
                    """
                    UPDATE request_engine.capacity_claims
                    SET status = 'released',
                        released_at = clock_timestamp()
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
                    SET status = 'cancelled',
                        cancelled_at = clock_timestamp(),
                        revision = revision + 1
                    WHERE organization_id = :organization_id
                      AND id = :reservation_id
                    """
                ),
                {
                    "organization_id": command.organization_id,
                    "reservation_id": command.reservation_id,
                },
            )

            await append_audit(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                command_name="booking.cancel_reservation",
                aggregate_kind="Reservation",
                aggregate_id=command.reservation_id,
                idempotency_id=idempotency_id,
                details={
                    "reason": command.reason,
                    "subject_party_id": str(subject_party_id),
                    "subject_authority": authority.audit_details(),
                    "expected_revision": command.expected_revision,
                },
            )
            await append_outbox(
                session,
                organization_id=command.organization_id,
                event_type="reservation.cancelled.v1",
                aggregate_kind="Reservation",
                aggregate_id=command.reservation_id,
                payload={
                    "reservation_id": str(command.reservation_id),
                    "reason": command.reason,
                },
            )
            reservation = await read_reservation(
                session,
                command.organization_id,
                command.reservation_id,
            )
            await complete_idempotency(
                session,
                idempotency_id,
                {"reservation": reservation_to_json(reservation)},
            )
            return reservation


async def load_bookable_offering(
    session: AsyncSession,
    organization_id: UUID,
    offering_version_id: UUID,
) -> RowMapping:
    row = (
        (
            await session.execute(
                text(
                    f"""
                    SELECT ov.duration_minutes, ov.bookable,
                           {EFFECTIVE_BOOKING_POLICY_SELECT}
                    FROM request_engine.offering_versions ov
                    WHERE ov.organization_id = :organization_id
                      AND ov.id = :offering_version_id
                    """
                ),
                {
                    "organization_id": organization_id,
                    "offering_version_id": offering_version_id,
                },
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise OfferingVersionNotFound(offering_version_id)
    if row["bookable"] is not True or row["duration_minutes"] is None:
        raise OfferingVersionNotBookable(offering_version_id)
    return row


async def validate_subject_location_and_origin(
    session: AsyncSession,
    *,
    organization_id: UUID,
    subject_party_id: UUID,
    location_id: UUID | None,
    origin_request_id: UUID | None,
) -> None:
    subject_exists = (
        await session.execute(
            text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM request_engine.parties
                    WHERE organization_id = :organization_id
                      AND id = :subject_party_id
                      AND active
                )
                """
            ),
            {
                "organization_id": organization_id,
                "subject_party_id": subject_party_id,
            },
        )
    ).scalar_one()
    if subject_exists is not True:
        raise InvalidResourceSelection("booking subject Party does not exist or is inactive")

    if location_id is not None:
        location_exists = (
            await session.execute(
                text(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM request_engine.locations
                        WHERE organization_id = :organization_id
                          AND id = :location_id
                          AND active
                    )
                    """
                ),
                {"organization_id": organization_id, "location_id": location_id},
            )
        ).scalar_one()
        if location_exists is not True:
            raise InvalidResourceSelection("booking Location does not exist or is inactive")

    if origin_request_id is not None:
        request_exists = (
            await session.execute(
                text(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM request_engine.requests
                        WHERE organization_id = :organization_id
                          AND id = :request_id
                    )
                    """
                ),
                {
                    "organization_id": organization_id,
                    "request_id": origin_request_id,
                },
            )
        ).scalar_one()
        if request_exists is not True:
            raise InvalidResourceSelection("origin Request does not exist")


async def load_requirements(
    session: AsyncSession,
    organization_id: UUID,
    offering_version_id: UUID,
) -> dict[UUID, _Requirement]:
    rows = (
        (
            await session.execute(
                text(
                    """
                    SELECT id, ordinal, capability_id, quantity
                    FROM request_engine.offering_resource_requirements
                    WHERE organization_id = :organization_id
                      AND offering_version_id = :offering_version_id
                    ORDER BY ordinal
                    """
                ),
                {
                    "organization_id": organization_id,
                    "offering_version_id": offering_version_id,
                },
            )
        )
        .mappings()
        .all()
    )
    if not rows:
        raise BookingConfigurationError(
            "bookable OfferingVersion requires at least one resource requirement"
        )
    return {
        cast(UUID, row["id"]): _Requirement(
            id=cast(UUID, row["id"]),
            ordinal=cast(int, row["ordinal"]),
            capability_id=cast(UUID, row["capability_id"]),
            quantity=cast(int, row["quantity"]),
        )
        for row in rows
    }


def validate_choice_cardinality(
    requirements: dict[UUID, _Requirement],
    choices: tuple[ResourceChoice, ...],
) -> dict[UUID, ResourceChoice]:
    by_requirement: dict[UUID, ResourceChoice] = {}
    for choice in choices:
        if choice.requirement_id in by_requirement:
            raise InvalidResourceSelection(
                f"requirement {choice.requirement_id} was selected more than once"
            )
        by_requirement[choice.requirement_id] = choice
    if set(by_requirement) != set(requirements):
        raise InvalidResourceSelection(
            "resource choices must satisfy every mandatory requirement exactly once"
        )
    return by_requirement


async def lock_resources(
    session: AsyncSession,
    *,
    organization_id: UUID,
    resource_ids: tuple[UUID, ...],
) -> dict[UUID, LockedResource]:
    unique_ids = tuple(sorted(set(resource_ids), key=str))
    rows = (
        (
            await session.execute(
                text(
                    """
                    SELECT id, capacity_model, capacity_units, active
                    FROM request_engine.resources
                    WHERE organization_id = :organization_id
                      AND id = ANY(CAST(:resource_ids AS uuid[]))
                    ORDER BY id
                    FOR UPDATE
                    """
                ),
                {
                    "organization_id": organization_id,
                    "resource_ids": [str(value) for value in unique_ids],
                },
            )
        )
        .mappings()
        .all()
    )
    if len(rows) != len(unique_ids):
        raise InvalidResourceSelection("one or more selected Resources do not exist")

    await _lock_shared_capacity_roots(session, organization_id, unique_ids)

    result: dict[UUID, LockedResource] = {}
    for row in rows:
        if row["active"] is not True:
            raise AppointmentUnavailable(f"Resource {row['id']} is inactive")
        resource = LockedResource(
            id=cast(UUID, row["id"]),
            capacity_model=CapacityModel(cast(str, row["capacity_model"])),
            capacity_units=cast(int, row["capacity_units"]),
        )
        result[resource.id] = resource
    return result


async def lock_resource_ids(
    session: AsyncSession,
    organization_id: UUID,
    resource_ids: tuple[UUID, ...],
) -> None:
    unique_ids = tuple(sorted(set(resource_ids), key=str))
    rows = (
        await session.execute(
            text(
                """
                SELECT id
                FROM request_engine.resources
                WHERE organization_id = :organization_id
                  AND id = ANY(CAST(:resource_ids AS uuid[]))
                ORDER BY id
                FOR UPDATE
                """
            ),
            {
                "organization_id": organization_id,
                "resource_ids": [str(value) for value in unique_ids],
            },
        )
    ).all()
    if len(rows) != len(unique_ids):
        raise BookingConfigurationError("Reservation references missing Resources")

    await _lock_shared_capacity_roots(session, organization_id, unique_ids)


async def _lock_shared_capacity_roots(
    session: AsyncSession,
    organization_id: UUID,
    resource_ids: tuple[UUID, ...],
) -> None:
    if not resource_ids:
        return
    await session.execute(
        text(
            """
            SELECT request_cmd.lock_shared_capacity_roots(
                :organization_id,
                CAST(:resource_ids AS uuid[])
            )
            """
        ),
        {
            "organization_id": organization_id,
            "resource_ids": [str(value) for value in resource_ids],
        },
    )


async def validate_resource_capabilities(
    session: AsyncSession,
    *,
    organization_id: UUID,
    requirements: dict[UUID, _Requirement],
    choices: dict[UUID, ResourceChoice],
    resources: dict[UUID, LockedResource],
    location_id: UUID | None,
) -> None:
    del location_id
    assignment_rows = (
        await session.execute(
            text(
                """
                SELECT resource_id, capability_id
                FROM request_engine.resource_capability_assignments
                WHERE organization_id = :organization_id
                  AND resource_id = ANY(CAST(:resource_ids AS uuid[]))
                """
            ),
            {
                "organization_id": organization_id,
                "resource_ids": [str(value) for value in resources],
            },
        )
    ).all()
    assignments = {(cast(UUID, row[0]), cast(UUID, row[1])) for row in assignment_rows}

    for requirement_id, choice in choices.items():
        requirement = requirements[requirement_id]
        resource = resources[choice.resource_id]
        if (resource.id, requirement.capability_id) not in assignments:
            raise InvalidResourceSelection(
                f"Resource {resource.id} does not satisfy requirement {requirement.id}"
            )


def revalidate_exact_slot(
    *,
    requirements: dict[UUID, _Requirement],
    choices: dict[UUID, ResourceChoice],
    profiles: dict[UUID, ResourceAvailability],
    start_at: object,
    end_at: object,
    duration_minutes: int,
    step_minutes: int,
) -> None:
    from datetime import datetime

    if not isinstance(start_at, datetime) or not isinstance(end_at, datetime):
        raise TypeError("start_at/end_at must be datetime")
    quantities_by_resource: dict[UUID, int] = defaultdict(int)
    requirements_by_resource: dict[UUID, int] = defaultdict(int)

    for requirement_id, choice in choices.items():
        requirement = requirements[requirement_id]
        profile = profiles[choice.resource_id]
        canonical = find_resource_intervals(
            profile,
            window_start=start_at,
            window_end=end_at,
            duration_minutes=duration_minutes,
            step_minutes=step_minutes,
            required_quantity=requirement.quantity,
        )
        if not canonical or canonical[0].start_at != start_at or canonical[0].end_at != end_at:
            raise AppointmentUnavailable(
                f"Resource {choice.resource_id} is not scheduled for the requested slot"
            )
        quantities_by_resource[choice.resource_id] += requirement.quantity
        requirements_by_resource[choice.resource_id] += 1

    for resource_id, total_quantity in quantities_by_resource.items():
        profile = profiles[resource_id]
        if (
            profile.capacity_model is CapacityModel.EXCLUSIVE
            and requirements_by_resource[resource_id] > 1
        ):
            raise InvalidResourceSelection(
                f"exclusive Resource {resource_id} cannot satisfy multiple "
                "simultaneous requirements"
            )
        if not interval_has_resource_capacity(
            profile,
            start_at=start_at,
            end_at=end_at,
            required_quantity=total_quantity,
        ):
            raise AppointmentUnavailable(f"Resource {resource_id} no longer has capacity")


def ensure_reservation_revision(
    row: RowMapping,
    reservation_id: UUID,
    expected_revision: int,
) -> None:
    current_revision = cast(int, row["revision"])
    if current_revision != expected_revision:
        raise ReservationRevisionConflict(
            reservation_id,
            expected_revision,
            current_revision,
        )


async def read_reservation(
    session: AsyncSession,
    organization_id: UUID,
    reservation_id: UUID,
) -> Reservation:
    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT reservation_id, offering_version_id, subject_party_id,
                           location_id, lower(during) AS start_at,
                           upper(during) AS end_at, status, revision,
                           attendance_status, estimated_arrival_at
                    FROM request_read.reservation_status_v1
                    WHERE organization_id = :organization_id
                      AND reservation_id = :reservation_id
                    """
                ),
                {
                    "organization_id": organization_id,
                    "reservation_id": reservation_id,
                },
            )
        )
        .mappings()
        .one()
    )
    return reservation_from_row(row)


def reservation_to_json(reservation: Reservation) -> dict[str, object]:
    return {
        "id": str(reservation.id),
        "offering_version_id": str(reservation.offering_version_id),
        "subject_party_id": str(reservation.subject_party_id),
        "location_id": str(reservation.location_id) if reservation.location_id else None,
        "start_at": reservation.start_at.isoformat(),
        "end_at": reservation.end_at.isoformat(),
        "status": reservation.status.value,
        "revision": reservation.revision,
        "attendance_status": reservation.attendance_status.value,
    }


def reservation_from_json(data: dict[str, object]) -> Reservation:
    from datetime import datetime

    from request_engine.modules.booking.contracts.appointments import (
        AttendanceStatus,
        ReservationStatus,
    )

    location_raw = cast(str | None, data["location_id"])
    return Reservation(
        id=UUID(cast(str, data["id"])),
        offering_version_id=UUID(cast(str, data["offering_version_id"])),
        subject_party_id=UUID(cast(str, data["subject_party_id"])),
        location_id=UUID(location_raw) if location_raw else None,
        start_at=datetime.fromisoformat(cast(str, data["start_at"])),
        end_at=datetime.fromisoformat(cast(str, data["end_at"])),
        status=ReservationStatus(cast(str, data["status"])),
        revision=cast(int, data["revision"]),
        attendance_status=AttendanceStatus(cast(str, data["attendance_status"])),
    )
