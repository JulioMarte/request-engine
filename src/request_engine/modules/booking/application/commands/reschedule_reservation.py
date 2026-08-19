from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from request_engine.modules.booking.contracts.appointments import Reservation, ResourceChoice


@dataclass(frozen=True, slots=True)
class RescheduleReservationCommand:
    organization_id: UUID
    principal_id: UUID
    reservation_id: UUID
    start_at: datetime
    resources: tuple[ResourceChoice, ...]
    idempotency_key: str
    expected_revision: int
    location_id: UUID | None = None
    allow_subject_override: bool = False


class RescheduleReservationHandler(Protocol):
    async def reschedule_reservation(
        self, command: RescheduleReservationCommand
    ) -> Reservation: ...


async def reschedule_reservation(
    handler: RescheduleReservationHandler,
    command: RescheduleReservationCommand,
) -> Reservation:
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    if command.expected_revision <= 0:
        raise ValueError("expected_revision must be positive")
    if not command.resources:
        raise ValueError("at least one ResourceChoice is required")
    return await handler.reschedule_reservation(command)
