from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from request_engine.modules.booking.contracts.appointments import Reservation


@dataclass(frozen=True, slots=True)
class ConfirmCapacityHoldCommand:
    organization_id: UUID
    principal_id: UUID
    hold_id: UUID
    idempotency_key: str
    origin_request_id: UUID | None = None


class ConfirmCapacityHoldHandler(Protocol):
    async def confirm_capacity_hold(self, command: ConfirmCapacityHoldCommand) -> Reservation: ...


async def confirm_capacity_hold(
    handler: ConfirmCapacityHoldHandler,
    command: ConfirmCapacityHoldCommand,
) -> Reservation:
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    return await handler.confirm_capacity_hold(command)
