from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.booking.application.errors import BookingConfigurationError, ReservationNotFound


async def lock_reservation_for_recovery(session: AsyncSession, organization_id: UUID, reservation_id: UUID) -> RowMapping:
    row = ((await session.execute(text("""SELECT id, offering_version_id, subject_party_id, location_id, origin_request_id, during, lower(during) AS start_at, upper(during) AS end_at, status, booking_policy_snapshot, revision FROM request_engine.reservations WHERE organization_id = :organization_id AND id = :reservation_id FOR UPDATE"""), {"organization_id": organization_id, "reservation_id": reservation_id})).mappings().first())
    if row is None:
        raise ReservationNotFound(reservation_id)
    return row


async def load_active_recovery_claims(session: AsyncSession, organization_id: UUID, reservation_id: UUID) -> tuple[RowMapping, ...]:
    rows = ((await session.execute(text("""SELECT id, resource_id, requirement_id, resource_location_assignment_id, quantity, lower(during) AS start_at, upper(during) AS end_at FROM request_engine.capacity_claims WHERE organization_id = :organization_id AND reservation_id = :reservation_id AND status = 'active' ORDER BY requirement_id"""), {"organization_id": organization_id, "reservation_id": reservation_id})).mappings().all())
    if not rows:
        raise BookingConfigurationError(f"Reservation {reservation_id} has no active claims")
    return tuple(rows)


def source_claims_are_contextual(claims: tuple[RowMapping, ...]) -> bool:
    return any(cast(UUID | None, row["resource_location_assignment_id"]) is not None for row in claims)
