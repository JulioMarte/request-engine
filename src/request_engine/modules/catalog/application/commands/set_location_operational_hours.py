from dataclasses import dataclass
from datetime import date, time
from typing import Protocol
from uuid import UUID

from request_engine.modules.catalog.application.errors import CatalogInvalidInput


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
        raise CatalogInvalidInput("idempotency_key is required")
    if command.expected_operational_revision <= 0:
        raise CatalogInvalidInput("expected_operational_revision must be positive")
    validate_location_hours_windows(command.windows)
    return await handler.set_location_operational_hours(command)


def validate_location_hours_windows(windows: tuple[LocationOperationalHoursInput, ...]) -> None:
    seen: set[LocationOperationalHoursInput] = set()
    for window in windows:
        if not 0 <= window.weekday <= 6:
            raise CatalogInvalidInput("weekday must be between 0 and 6")
        if window.local_start.tzinfo is not None or window.local_end.tzinfo is not None:
            raise CatalogInvalidInput("hours require local wall-clock time without an offset")
        if window.local_start >= window.local_end:
            raise CatalogInvalidInput("local_start must be before local_end")
        if (
            window.valid_from is not None
            and window.valid_until is not None
            and window.valid_until < window.valid_from
        ):
            raise CatalogInvalidInput("valid_until cannot be before valid_from")
        if window in seen:
            raise CatalogInvalidInput("duplicate operational-hours window")
        seen.add(window)
