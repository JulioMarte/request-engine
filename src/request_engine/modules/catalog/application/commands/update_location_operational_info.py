from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from request_engine.modules.catalog.application.errors import CatalogInvalidInput


@dataclass(frozen=True, slots=True)
class LocationOperationalInfoState:
    location_id: UUID
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
    display_name: str | None = None


@dataclass(frozen=True, slots=True)
class UpdateLocationOperationalInfoCommand:
    organization_id: UUID
    principal_id: UUID
    authority_party_id: UUID
    location_id: UUID
    timezone: str
    active: bool
    expected_operational_revision: int
    idempotency_key: str
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
    display_name: str | None = None


class UpdateLocationOperationalInfoHandler(Protocol):
    async def update_location_operational_info(
        self, command: UpdateLocationOperationalInfoCommand
    ) -> LocationOperationalInfoState: ...


async def update_location_operational_info(
    handler: UpdateLocationOperationalInfoHandler,
    command: UpdateLocationOperationalInfoCommand,
) -> LocationOperationalInfoState:
    if not command.idempotency_key:
        raise CatalogInvalidInput("idempotency_key is required")
    if command.expected_operational_revision <= 0:
        raise CatalogInvalidInput("expected_operational_revision must be positive")
    if not command.timezone.strip():
        raise CatalogInvalidInput("timezone is required")
    if command.display_name is not None:
        validate_display_name(command.display_name)
    if (command.latitude is None) != (command.longitude is None):
        raise CatalogInvalidInput("latitude and longitude must be present together")
    if command.latitude is not None and not Decimal("-90") <= command.latitude <= Decimal("90"):
        raise CatalogInvalidInput("latitude must be between -90 and 90")
    if command.longitude is not None and not Decimal("-180") <= command.longitude <= Decimal("180"):
        raise CatalogInvalidInput("longitude must be between -180 and 180")
    if command.country_code is not None and (
        len(command.country_code) != 2 or command.country_code != command.country_code.upper()
    ):
        raise CatalogInvalidInput("country_code must be a two-letter uppercase code")
    return await handler.update_location_operational_info(command)


def validate_display_name(value: str) -> str:
    """Admit an owner-facing label: trimmed, 1..200 characters, no control characters."""

    cleaned = value.strip()
    if not cleaned:
        raise CatalogInvalidInput("display_name cannot be blank")
    if len(cleaned) > 200:
        raise CatalogInvalidInput("display_name cannot exceed 200 characters")
    if any(ord(character) < 32 or ord(character) == 127 for character in cleaned):
        raise CatalogInvalidInput("display_name cannot contain control characters")
    return cleaned
