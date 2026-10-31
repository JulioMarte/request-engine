"""Owner-authorized inventory of saved Location hours exceptions (with ids)."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class LocationHoursExceptionQuery:
    organization_id: UUID
    principal_id: UUID
    authority_party_id: UUID
    location_id: UUID
    include_inactive: bool = False
    limit: int = 50
    after: UUID | None = None


@dataclass(frozen=True, slots=True)
class LocationHoursExceptionItem:
    exception_id: UUID
    location_id: UUID
    start_at: datetime
    end_at: datetime
    exception_kind: Literal["available", "unavailable"]
    reason: str | None
    active: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class LocationHoursExceptionPage:
    """``items`` may hold ``limit + 1`` rows; the transport derives the cursor."""

    operational_revision: int
    items: tuple[LocationHoursExceptionItem, ...]


class LocationHoursExceptionReader(Protocol):
    async def location_hours_exceptions(
        self, query: LocationHoursExceptionQuery
    ) -> LocationHoursExceptionPage | None:
        """Return None when the Location is absent or foreign."""
        ...
