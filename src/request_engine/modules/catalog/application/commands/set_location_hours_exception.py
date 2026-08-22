from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

LocationHoursExceptionKind = Literal["available", "unavailable"]


@dataclass(frozen=True, slots=True)
class LocationHoursExceptionState:
    exception_id: UUID
    location_id: UUID
    start_at: datetime
    end_at: datetime
    exception_kind: LocationHoursExceptionKind
    reason: str | None
    active: bool
    operational_revision: int


@dataclass(frozen=True, slots=True)
class SetLocationHoursExceptionCommand:
    organization_id: UUID
    principal_id: UUID
    authority_party_id: UUID
    location_id: UUID
    start_at: datetime
    end_at: datetime
    exception_kind: LocationHoursExceptionKind
    expected_operational_revision: int
    idempotency_key: str
    exception_id: UUID | None = None
    reason: str | None = None
    active: bool = True


class SetLocationHoursExceptionHandler(Protocol):
    async def set_location_hours_exception(
        self, command: SetLocationHoursExceptionCommand
    ) -> LocationHoursExceptionState: ...


async def set_location_hours_exception(
    handler: SetLocationHoursExceptionHandler,
    command: SetLocationHoursExceptionCommand,
) -> LocationHoursExceptionState:
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    if command.expected_operational_revision <= 0:
        raise ValueError("expected_operational_revision must be positive")
    if command.exception_kind not in ("available", "unavailable"):
        raise ValueError("exception_kind must be available or unavailable")
    if command.start_at.tzinfo is None or command.start_at.utcoffset() is None:
        raise ValueError("start_at must be timezone-aware")
    if command.end_at.tzinfo is None or command.end_at.utcoffset() is None:
        raise ValueError("end_at must be timezone-aware")
    if command.end_at <= command.start_at:
        raise ValueError("end_at must be after start_at")
    if command.reason is not None and not command.reason.strip():
        raise ValueError("reason cannot be blank")
    return await handler.set_location_hours_exception(command)
