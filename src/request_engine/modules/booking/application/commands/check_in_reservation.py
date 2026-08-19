from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from request_engine.modules.booking.contracts.attendance import ReservationAttendanceState


@dataclass(frozen=True, slots=True)
class CheckInReservationCommand:
    organization_id: UUID
    principal_id: UUID
    reservation_id: UUID
    source_key: str
    idempotency_key: str
    expected_revision: int
    allow_subject_override: bool = False


class CheckInReservationHandler(Protocol):
    async def check_in_reservation(
        self,
        command: CheckInReservationCommand,
    ) -> ReservationAttendanceState: ...


async def check_in_reservation(
    handler: CheckInReservationHandler,
    command: CheckInReservationCommand,
) -> ReservationAttendanceState:
    if command.expected_revision <= 0:
        raise ValueError("expected_revision must be positive")
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    if not command.source_key:
        raise ValueError("source_key is required")
    return await handler.check_in_reservation(command)
