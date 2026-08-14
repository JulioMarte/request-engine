from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from request_engine.modules.booking.contracts.attendance import ReservationAttendanceState


@dataclass(frozen=True, slots=True)
class RecordAttendanceResponseCommand:
    organization_id: UUID
    principal_id: UUID
    reservation_id: UUID
    response: Literal["accepted", "declined"]
    source_key: str
    idempotency_key: str
    expected_revision: int
    allow_subject_override: bool = False


class RecordAttendanceResponseHandler(Protocol):
    async def record_attendance_response(
        self,
        command: RecordAttendanceResponseCommand,
    ) -> ReservationAttendanceState: ...


async def record_attendance_response(
    handler: RecordAttendanceResponseHandler,
    command: RecordAttendanceResponseCommand,
) -> ReservationAttendanceState:
    if command.expected_revision <= 0:
        raise ValueError("expected_revision must be positive")
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    if not command.source_key:
        raise ValueError("source_key is required")
    return await handler.record_attendance_response(command)


async def confirm_attendance(
    handler: RecordAttendanceResponseHandler,
    *,
    organization_id: UUID,
    principal_id: UUID,
    reservation_id: UUID,
    source_key: str,
    idempotency_key: str,
    expected_revision: int,
    allow_subject_override: bool = False,
) -> ReservationAttendanceState:
    return await record_attendance_response(
        handler,
        RecordAttendanceResponseCommand(
            organization_id=organization_id,
            principal_id=principal_id,
            reservation_id=reservation_id,
            response="accepted",
            source_key=source_key,
            idempotency_key=idempotency_key,
            expected_revision=expected_revision,
            allow_subject_override=allow_subject_override,
        ),
    )


async def decline_attendance(
    handler: RecordAttendanceResponseHandler,
    *,
    organization_id: UUID,
    principal_id: UUID,
    reservation_id: UUID,
    source_key: str,
    idempotency_key: str,
    expected_revision: int,
    allow_subject_override: bool = False,
) -> ReservationAttendanceState:
    return await record_attendance_response(
        handler,
        RecordAttendanceResponseCommand(
            organization_id=organization_id,
            principal_id=principal_id,
            reservation_id=reservation_id,
            response="declined",
            source_key=source_key,
            idempotency_key=idempotency_key,
            expected_revision=expected_revision,
            allow_subject_override=allow_subject_override,
        ),
    )
