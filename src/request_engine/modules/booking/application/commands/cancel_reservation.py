from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from request_engine.modules.booking.contracts.appointments import Reservation


@dataclass(frozen=True, slots=True)
class CancelReservationCommand:
    organization_id: UUID
    principal_id: UUID
    reservation_id: UUID
    idempotency_key: str
    reason: str | None = None


class CancelReservationHandler(Protocol):
    async def cancel_reservation(self, command: CancelReservationCommand) -> Reservation: ...


async def cancel_reservation(
    handler: CancelReservationHandler,
    command: CancelReservationCommand,
) -> Reservation:
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    return await handler.cancel_reservation(command)
