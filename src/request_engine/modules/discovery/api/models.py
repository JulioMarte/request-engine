from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

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


class DiscoveryOptionView(BaseModel):
    organization_id: UUID
    organization_key: str
    organization_display_name: str
    offering_id: UUID
    offering_key: str
    offering_display_name: str
    offering_version_id: UUID
    location_id: UUID
    location_key: str
    location_display_name: str
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
        if slot.planned_duration_minutes is None or slot.amount is None or slot.currency is None:
            raise ValueError("discovery option is missing deterministic commercial terms")
        return cls(
            organization_id=candidate.organization_id,
            organization_key=candidate.organization_key,
            organization_display_name=candidate.organization_display_name,
            offering_id=candidate.offering_id,
            offering_key=candidate.offering_key,
            offering_display_name=candidate.offering_display_name,
            offering_version_id=candidate.offering_version_id,
            location_id=candidate.location_id,
            location_key=candidate.location_key,
            location_display_name=candidate.location_display_name,
            distance_meters=candidate.distance_meters,
            start_at=slot.start_at,
            end_at=slot.end_at,
            planned_duration_minutes=slot.planned_duration_minutes,
            amount=slot.amount,
            currency=slot.currency,
            option_id=option_id,
        )
