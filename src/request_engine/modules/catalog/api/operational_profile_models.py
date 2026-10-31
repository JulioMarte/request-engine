from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class LocationBody(BaseModel):
    authority_party_id: UUID
    location_key: str
    display_name: str
    timezone: str
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


class LocationUpdateBody(BaseModel):
    authority_party_id: UUID
    timezone: str
    active: bool
    expected_operational_revision: int
    display_name: str | None = Field(
        default=None,
        max_length=200,
        description="New Location label; omitted or null keeps the current name. "
        "Not booking-material: it does not advance operational_revision.",
    )
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


class ContactBody(BaseModel):
    channel: Literal["phone", "whatsapp", "email"]
    value: str
    label: str | None = None


class LocationContactsBody(BaseModel):
    authority_party_id: UUID
    contacts: tuple[ContactBody, ...]
