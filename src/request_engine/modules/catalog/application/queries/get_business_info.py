from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class PublicContactEndpoint:
    channel: str
    value: str
    label: str | None = None


@dataclass(frozen=True, slots=True)
class OperationalHoursWindow:
    weekday: int
    local_start: time
    local_end: time
    valid_from: date | None = None
    valid_until: date | None = None


@dataclass(frozen=True, slots=True)
class OperationalHoursException:
    start_at: datetime
    end_at: datetime
    kind: str


@dataclass(frozen=True, slots=True)
class BusinessLocation:
    id: UUID
    location_key: str
    display_name: str
    timezone: str
    public_data: dict[str, object]
    address_line1: str | None = None
    address_line2: str | None = None
    locality: str | None = None
    administrative_area: str | None = None
    postal_code: str | None = None
    country_code: str | None = None
    contacts: tuple[PublicContactEndpoint, ...] = ()
    operational_hours: tuple[OperationalHoursWindow, ...] = ()
    hours_exceptions: tuple[OperationalHoursException, ...] = ()


@dataclass(frozen=True, slots=True)
class BusinessInfo:
    organization_id: UUID
    organization_key: str
    display_name: str
    public_profile: dict[str, object]
    locations: tuple[BusinessLocation, ...]
    legal_name: str | None = None
    default_timezone: str | None = None
    default_locale: str | None = None
    default_currency: str | None = None
    operational_status: str = "active"
    contacts: tuple[PublicContactEndpoint, ...] = ()


class BusinessInfoReader(Protocol):
    async def get_business_info(self, organization_id: UUID) -> BusinessInfo: ...


async def get_business_info(
    reader: BusinessInfoReader,
    organization_id: UUID,
) -> BusinessInfo:
    """Return tenant-scoped public operational truth plus released V3 compatibility data."""

    return await reader.get_business_info(organization_id)
