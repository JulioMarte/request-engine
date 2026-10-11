"""Current administrative inventory, separate from public active-only discovery."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class CatalogAdministrationQuery:
    organization_id: UUID
    principal_id: UUID
    authority_party_id: UUID
    limit: int = 50
    after: UUID | None = None
    target_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class AdministrativeLocation:
    location_id: UUID
    location_key: str
    display_name: str
    timezone: str
    active: bool
    operational_revision: int
    address_line1: str | None
    address_line2: str | None
    locality: str | None
    administrative_area: str | None
    postal_code: str | None
    country_code: str | None
    latitude: Decimal | None
    longitude: Decimal | None
    geocoding_source: str | None
    geocoded_at: datetime | None


@dataclass(frozen=True, slots=True)
class AdministrativeOffering:
    offering_id: UUID
    offering_key: str
    display_name: str
    description: str | None
    active: bool
    offering_version_id: UUID
    version: int
    duration_minutes: int | None
    bookable: bool
    requestable: bool
    booking_policy_revision: int


class CatalogAdministrationReader(Protocol):
    async def locations(
        self, query: CatalogAdministrationQuery
    ) -> tuple[AdministrativeLocation, ...]: ...

    async def offerings(
        self, query: CatalogAdministrationQuery
    ) -> tuple[AdministrativeOffering, ...]: ...
