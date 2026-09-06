from datetime import datetime, timedelta
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from request_engine.modules.discovery.application.queries.search_supply import DiscoveryOption


class SearchPublishedSupplyBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    service_classification_key: str = Field(
        min_length=1,
        max_length=120,
        pattern=r"^[a-z0-9]+(?:_[a-z0-9]+)*$",
    )
    origin_latitude: Decimal = Field(ge=-90, le=90)
    origin_longitude: Decimal = Field(ge=-180, le=180)
    radius_meters: int = Field(gt=0, le=100_000)
    window_start: datetime
    window_end: datetime
    limit: int = Field(default=50, ge=1, le=100)

    @model_validator(mode="after")
    def validate_window(self) -> "SearchPublishedSupplyBody":
        if self.window_start.utcoffset() is None or self.window_end.utcoffset() is None:
            raise ValueError("window_start and window_end must be timezone-aware")
        if self.window_end <= self.window_start:
            raise ValueError("window_end must be after window_start")
        if self.window_end - self.window_start > timedelta(days=7):
            raise ValueError("discovery window cannot exceed 7 days")
        return self


class PublicLocationAddressView(BaseModel):
    address_line1: str | None = None
    address_line2: str | None = None
    locality: str | None = None
    administrative_area: str | None = None
    postal_code: str | None = None
    country_code: str | None = None


class PublicProviderView(BaseModel):
    resource_key: str
    display_name: str
    role_label: str | None = None
    profile_image_ref: str | None = None


class DiscoveryOptionView(BaseModel):
    organization_key: str
    organization_display_name: str
    offering_key: str
    offering_display_name: str
    location_key: str
    location_display_name: str
    location_address: PublicLocationAddressView
    provider: PublicProviderView | None
    distance_meters: float
    start_at: datetime
    end_at: datetime
    planned_duration_minutes: int
    amount: Decimal
    currency: str
    option_id: str

    @classmethod
    def from_option(cls, item: DiscoveryOption, option_id: str) -> "DiscoveryOptionView":
        candidate = item.candidate
        slot = item.slot

        provider: PublicProviderView | None = None
        if candidate.provider_visibility == "public":
            if candidate.provider_key is None or candidate.provider_display_name is None:
                raise ValueError(
                    "public provider publication is missing its accepted public profile"
                )
            provider = PublicProviderView(
                resource_key=candidate.provider_key,
                display_name=candidate.provider_display_name,
                role_label=candidate.provider_role_label,
                profile_image_ref=candidate.provider_profile_image_ref,
            )

        return cls(
            organization_key=candidate.organization_key,
            organization_display_name=candidate.organization_display_name,
            offering_key=candidate.offering_key,
            offering_display_name=candidate.offering_display_name,
            location_key=candidate.location_key,
            location_display_name=candidate.location_display_name,
            location_address=PublicLocationAddressView(
                address_line1=candidate.location_address_line1,
                address_line2=candidate.location_address_line2,
                locality=candidate.location_locality,
                administrative_area=candidate.location_administrative_area,
                postal_code=candidate.location_postal_code,
                country_code=candidate.location_country_code,
            ),
            provider=provider,
            distance_meters=candidate.distance_meters,
            start_at=slot.start_at,
            end_at=slot.end_at,
            planned_duration_minutes=slot.planned_duration_minutes,
            amount=slot.amount,
            currency=slot.currency,
            option_id=option_id,
        )
