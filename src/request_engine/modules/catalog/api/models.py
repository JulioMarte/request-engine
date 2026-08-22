from datetime import date, datetime, time
from uuid import UUID

from pydantic import BaseModel

from request_engine.modules.catalog.application.queries.get_business_info import BusinessInfo


class PublicContactEndpointView(BaseModel):
    channel: str
    value: str
    label: str | None = None


class OperationalHoursWindowView(BaseModel):
    weekday: int
    local_start: time
    local_end: time
    valid_from: date | None = None
    valid_until: date | None = None


class OperationalHoursExceptionView(BaseModel):
    start_at: datetime
    end_at: datetime
    kind: str


class BusinessLocationView(BaseModel):
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
    contacts: tuple[PublicContactEndpointView, ...] = ()
    operational_hours: tuple[OperationalHoursWindowView, ...] = ()
    hours_exceptions: tuple[OperationalHoursExceptionView, ...] = ()


class BusinessInfoView(BaseModel):
    organization_id: UUID
    organization_key: str
    display_name: str
    public_profile: dict[str, object]
    legal_name: str | None = None
    default_timezone: str | None = None
    default_locale: str | None = None
    default_currency: str | None = None
    operational_status: str
    contacts: tuple[PublicContactEndpointView, ...] = ()
    locations: tuple[BusinessLocationView, ...]

    @classmethod
    def from_contract(cls, info: BusinessInfo) -> "BusinessInfoView":
        return cls(
            organization_id=info.organization_id,
            organization_key=info.organization_key,
            display_name=info.display_name,
            public_profile=info.public_profile,
            legal_name=info.legal_name,
            default_timezone=info.default_timezone,
            default_locale=info.default_locale,
            default_currency=info.default_currency,
            operational_status=info.operational_status,
            contacts=tuple(
                PublicContactEndpointView(
                    channel=item.channel,
                    value=item.value,
                    label=item.label,
                )
                for item in info.contacts
            ),
            locations=tuple(
                BusinessLocationView(
                    id=item.id,
                    location_key=item.location_key,
                    display_name=item.display_name,
                    timezone=item.timezone,
                    public_data=item.public_data,
                    address_line1=item.address_line1,
                    address_line2=item.address_line2,
                    locality=item.locality,
                    administrative_area=item.administrative_area,
                    postal_code=item.postal_code,
                    country_code=item.country_code,
                    contacts=tuple(
                        PublicContactEndpointView(
                            channel=contact.channel,
                            value=contact.value,
                            label=contact.label,
                        )
                        for contact in item.contacts
                    ),
                    operational_hours=tuple(
                        OperationalHoursWindowView(
                            weekday=window.weekday,
                            local_start=window.local_start,
                            local_end=window.local_end,
                            valid_from=window.valid_from,
                            valid_until=window.valid_until,
                        )
                        for window in item.operational_hours
                    ),
                    hours_exceptions=tuple(
                        OperationalHoursExceptionView(
                            start_at=exception.start_at,
                            end_at=exception.end_at,
                            kind=exception.kind,
                        )
                        for exception in item.hours_exceptions
                    ),
                )
                for item in info.locations
            ),
        )
