from dataclasses import dataclass
from datetime import date, time
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class LocationOperationalHoursInput:
    weekday: int
    local_start: time
    local_end: time
    valid_from: date | None = None
    valid_until: date | None = None


@dataclass(frozen=True, slots=True)
class LocationOperationalHoursState:
    location_id: UUID
    operational_revision: int
    windows: tuple[LocationOperationalHoursInput, ...]


@dataclass(frozen=True, slots=True)
class SetLocationOperationalHoursCommand:
    organization_id: UUID
    principal_id: UUID
    authority_party_id: UUID
    location_id: UUID
    expected_operational_revision: int
    windows: tuple[LocationOperationalHoursInput, ...]
    idempotency_key: str


class SetLocationOperationalHoursHandler(Protocol):
    async def set_location_operational_hours(
        self,
        command: SetLocationOperationalHoursCommand,
    ) -> LocationOperationalHoursState: ...


async def set_location_operational_hours(
    handler: SetLocationOperationalHoursHandler,
    command: SetLocationOperationalHoursCommand,
) -> LocationOperationalHoursState:
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    if command.expected_operational_revision <= 0:
        raise ValueError("expected_operational_revision must be positive")
    return await handler.set_location_operational_hours(command)
