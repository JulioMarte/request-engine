from dataclasses import dataclass
from datetime import date, time
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ResourceLocationAvailabilityWindow:
    weekday: int
    local_start: time
    local_end: time
    valid_from: date | None = None
    valid_until: date | None = None


@dataclass(frozen=True, slots=True)
class ResourceLocationAvailabilityState:
    assignment_id: UUID
    windows: tuple[ResourceLocationAvailabilityWindow, ...]
    resource_availability_revision: int


@dataclass(frozen=True, slots=True)
class SetResourceLocationAvailabilityCommand:
    organization_id: UUID
    principal_id: UUID
    authority_party_id: UUID
    assignment_id: UUID
    windows: tuple[ResourceLocationAvailabilityWindow, ...]
    expected_resource_availability_revision: int
    idempotency_key: str


class SetResourceLocationAvailabilityHandler(Protocol):
    async def set_resource_location_availability(
        self, command: SetResourceLocationAvailabilityCommand
    ) -> ResourceLocationAvailabilityState: ...


async def set_resource_location_availability(
    handler: SetResourceLocationAvailabilityHandler,
    command: SetResourceLocationAvailabilityCommand,
) -> ResourceLocationAvailabilityState:
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    if command.expected_resource_availability_revision <= 0:
        raise ValueError("expected_resource_availability_revision must be positive")
    for window in command.windows:
        if window.weekday < 0 or window.weekday > 6:
            raise ValueError("weekday must be between 0 and 6")
        if window.local_start >= window.local_end:
            raise ValueError("local_start must be before local_end")
        if (
            window.valid_from is not None
            and window.valid_until is not None
            and window.valid_until < window.valid_from
        ):
            raise ValueError("valid_until must be on or after valid_from")
    return await handler.set_resource_location_availability(command)
