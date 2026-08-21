from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

ExceptionKind = Literal["available", "unavailable"]


@dataclass(frozen=True, slots=True)
class ResourceLocationScheduleExceptionState:
    exception_id: UUID
    assignment_id: UUID
    start_at: datetime
    end_at: datetime
    exception_kind: ExceptionKind
    reason: str | None
    active: bool
    resource_availability_revision: int


@dataclass(frozen=True, slots=True)
class SetResourceLocationScheduleExceptionCommand:
    organization_id: UUID
    principal_id: UUID
    authority_party_id: UUID
    assignment_id: UUID
    start_at: datetime
    end_at: datetime
    exception_kind: ExceptionKind
    expected_resource_availability_revision: int
    idempotency_key: str
    exception_id: UUID | None = None
    reason: str | None = None
    active: bool = True


class SetResourceLocationScheduleExceptionHandler(Protocol):
    async def set_resource_location_schedule_exception(
        self, command: SetResourceLocationScheduleExceptionCommand
    ) -> ResourceLocationScheduleExceptionState: ...


async def set_resource_location_schedule_exception(
    handler: SetResourceLocationScheduleExceptionHandler,
    command: SetResourceLocationScheduleExceptionCommand,
) -> ResourceLocationScheduleExceptionState:
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    if command.expected_resource_availability_revision <= 0:
        raise ValueError("expected_resource_availability_revision must be positive")
    if command.exception_kind not in ("available", "unavailable"):
        raise ValueError("exception_kind must be available or unavailable")
    if command.reason is not None and not command.reason.strip():
        raise ValueError("reason cannot be blank")
    return await handler.set_resource_location_schedule_exception(command)
