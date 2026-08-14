from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from request_engine.modules.booking.contracts.attendance import ReservationAttendanceState


@dataclass(frozen=True, slots=True)
class EvaluateNoShowCommand:
    organization_id: UUID
    principal_id: UUID
    reservation_id: UUID
    idempotency_key: str


class EvaluateNoShowHandler(Protocol):
    async def evaluate_no_show(
        self,
        command: EvaluateNoShowCommand,
    ) -> ReservationAttendanceState: ...


async def evaluate_no_show(
    handler: EvaluateNoShowHandler,
    command: EvaluateNoShowCommand,
) -> ReservationAttendanceState:
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    return await handler.evaluate_no_show(command)
