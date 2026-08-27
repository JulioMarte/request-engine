from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.booking.adapters.db.reservation_commands import LockedResource
from request_engine.modules.booking.adapters.db.resource_availability import (
    load_live_capacity_claims,
    load_resource_exceptions,
    load_resource_schedules,
)
from request_engine.modules.booking.application.errors import (
    BookingConfigurationError,
    ReservationNotFound,
)
from request_engine.modules.booking.domain.availability import ResourceAvailability


async def lock_reservation_for_recovery(
    session: AsyncSession,
    organization_id: UUID,
    reservation_id: UUID,
) -> RowMapping:
    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT id,
                           offering_version_id,
                           subject_party_id,
                           location_id,
                           origin_request_id,
                           during,
                           lower(during) AS start_at,
                           upper(during) AS end_at,
                           status,
                           booking_policy_snapshot,
                           revision
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


async def load_active_recovery_claims(
    session: AsyncSession,
    organization_id: UUID,
    reservation_id: UUID,
) -> tuple[RowMapping, ...]:
    rows = (
        (
            await session.execute(
                text(
                    """
                    SELECT id,
                           resource_id,
                           requirement_id,
                           resource_location_assignment_id,
                           quantity,
                           lower(during) AS start_at,
                           upper(during) AS end_at
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
        raise BookingConfigurationError(
            f"Reservation {reservation_id} has no active claims"
        )
    return tuple(rows)


async def load_recovery_profiles_excluding_reservation(
    session: AsyncSession,
    *,
    organization_id: UUID,
    resources: dict[UUID, LockedResource],
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
    return {
        resource_id: ResourceAvailability(
            capacity_model=resource.capacity_model,
            capacity_units=resource.capacity_units,
            default_timezone=resource.default_timezone,
            schedules=schedules.get(resource_id, ()),
            exceptions=exceptions.get(resource_id, ()),
            live_claims=claims.get(resource_id, ()),
        )
        for resource_id, resource in resources.items()
    }


def source_claims_are_contextual(claims: tuple[RowMapping, ...]) -> bool:
    return any(
        cast(UUID | None, row["resource_location_assignment_id"]) is not None
        for row in claims
    )
