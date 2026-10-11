from datetime import date, datetime, time
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class LocationOperationalInfoView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
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


class CreatedLocationView(LocationOperationalInfoView):
    location_key: str
    display_name: str


class LocationContactView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    channel: Literal["phone", "whatsapp", "email"]
    normalized_value: str
    label: str | None


class LocationPublicContactsView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    location_id: UUID
    contacts: tuple[LocationContactView, ...]


class LocationHoursWindowView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    weekday: int
    local_start: time
    local_end: time
    valid_from: date | None
    valid_until: date | None


class LocationOperationalHoursView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    location_id: UUID
    operational_revision: int
    windows: tuple[LocationHoursWindowView, ...]


class LocationHoursExceptionView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    exception_id: UUID
    location_id: UUID
    start_at: datetime
    end_at: datetime
    exception_kind: Literal["available", "unavailable"]
    reason: str | None
    active: bool
    operational_revision: int


class OfferingVersionBookingTermsView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    terms_id: UUID
    offering_version_id: UUID
    amount: Decimal
    currency: str


class OrganizationHolidayView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    date: date
    reason: str | None


class DeclaredOrganizationHolidaysView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    holidays: tuple[OrganizationHolidayView, ...]
    locations_covered: int
    exceptions_created: int
    exceptions_already_declared: int
