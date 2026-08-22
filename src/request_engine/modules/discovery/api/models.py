from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from request_engine.modules.discovery.application.queries.search_supply import DiscoveryOption


class SearchPublishedSupplyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service_classification_key: str = Field(min_length=1, max_length=120)
    origin_latitude: Decimal = Field(ge=-90, le=90)
    origin_longitude: Decimal = Field(ge=-180, le=180)
    radius_meters: int = Field(gt=0, le=100_000)
    window_start: datetime
    window_end: datetime
    limit: int = Field(default=50, ge=1, le=100)


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
    planned_duration_minutes: int | None = None
    amount: Decimal | None = None
    currency: str | None = None
    option_id: str

    @classmethod
    def from_option(cls, item: DiscoveryOption, option_id: str) -> "DiscoveryOptionView":
        candidate = item.candidate
        slot = item.slot
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
