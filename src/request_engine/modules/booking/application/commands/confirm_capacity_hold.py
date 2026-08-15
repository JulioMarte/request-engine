from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from request_engine.modules.booking.contracts.appointments import Reservation


@dataclass(frozen=True, slots=True)
class ConfirmCapacityHoldCommand:
    organization_id: UUID
    principal_id: UUID
    hold_id: UUID
    expected_revision: int
    idempotency_key: str
    origin_request_id: UUID | None = None
    allow_subject_override: bool = False


class ConfirmCapacityHoldHandler(Protocol):
    async def confirm_capacity_hold(self, command: ConfirmCapacityHoldCommand) -> Reservation: ...


async def confirm_capacity_hold(
    handler: ConfirmCapacityHoldHandler,
    command: ConfirmCapacityHoldCommand,
) -> Reservation:
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    if command.expected_revision <= 0:
        raise ValueError("expected_revision must be positive")
    return await handler.confirm_capacity_hold(command)
