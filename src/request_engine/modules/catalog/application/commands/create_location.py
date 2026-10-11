from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from request_engine.modules.catalog.application.errors import CatalogInvalidInput


@dataclass(frozen=True, slots=True)
class CreatedLocationState:
    location_id: UUID
    location_key: str
    display_name: str
    timezone: str
    active: bool
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
    operational_revision: int


@dataclass(frozen=True, slots=True)
class CreateLocationCommand:
    organization_id: UUID
    principal_id: UUID
    authority_party_id: UUID
    location_key: str
    display_name: str
    timezone: str
    idempotency_key: str
    active: bool = True
    address_line1: str | None = None
    address_line2: str | None = None
    locality: str | None = None
    administrative_area: str | None = None
    postal_code: str | None = None
    country_code: str | None = None
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    geocoding_source: str | None = None
    geocoded_at: datetime | None = None


class CreateLocationHandler(Protocol):
    async def create_location(self, command: CreateLocationCommand) -> CreatedLocationState: ...


async def create_location(
    handler: CreateLocationHandler,
    command: CreateLocationCommand,
) -> CreatedLocationState:
    if not command.idempotency_key:
        raise CatalogInvalidInput("idempotency_key is required")
    if not command.location_key.strip():
        raise CatalogInvalidInput("location_key is required")
    if not command.display_name.strip():
        raise CatalogInvalidInput("display_name is required")
    if not command.timezone.strip():
        raise CatalogInvalidInput("timezone is required")
    if (command.latitude is None) != (command.longitude is None):
        raise CatalogInvalidInput("latitude and longitude must be present together")
    if command.latitude is not None and not (Decimal("-90") <= command.latitude <= Decimal("90")):
        raise CatalogInvalidInput("latitude must be between -90 and 90")
    if command.longitude is not None and not (
        Decimal("-180") <= command.longitude <= Decimal("180")
    ):
        raise CatalogInvalidInput("longitude must be between -180 and 180")
    if command.country_code is not None and (
        len(command.country_code) != 2 or command.country_code != command.country_code.upper()
    ):
        raise CatalogInvalidInput("country_code must be a two-letter uppercase code")
    return await handler.create_location(command)
