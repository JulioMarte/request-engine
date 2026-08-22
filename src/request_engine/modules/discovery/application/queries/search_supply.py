from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

from request_engine.modules.booking.contracts.appointments import AppointmentSlot

MAX_RADIUS_METERS = 100_000
MAX_WINDOW = timedelta(days=7)
MAX_RESULTS = 100


@dataclass(frozen=True, slots=True)
class SearchPublishedSupplyQuery:
    service_classification_key: str
    origin_latitude: Decimal
    origin_longitude: Decimal
    radius_meters: int
    window_start: datetime
    window_end: datetime
    limit: int = 50


@dataclass(frozen=True, slots=True)
class DiscoveryCandidate:
    publication_id: UUID
    publication_revision: int
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
    resource_id: UUID | None
    provider_visibility: str
    publication_start: datetime
    publication_end: datetime | None
    distance_meters: float


@dataclass(frozen=True, slots=True)
class DiscoveryOption:
    candidate: DiscoveryCandidate
    slot: AppointmentSlot


def validate_search_query(query: SearchPublishedSupplyQuery) -> None:
    if not query.service_classification_key.strip():
        raise ValueError("service_classification_key is required")
    if query.origin_latitude < -90 or query.origin_latitude > 90:
        raise ValueError("origin_latitude must be between -90 and 90")
    if query.origin_longitude < -180 or query.origin_longitude > 180:
        raise ValueError("origin_longitude must be between -180 and 180")
    if not 0 < query.radius_meters <= MAX_RADIUS_METERS:
        raise ValueError(f"radius_meters must be between 1 and {MAX_RADIUS_METERS}")
    if query.window_start.tzinfo is None or query.window_end.tzinfo is None:
        raise ValueError("discovery window datetimes must be timezone-aware")
    if query.window_end <= query.window_start:
        raise ValueError("window_end must be after window_start")
    if query.window_end - query.window_start > MAX_WINDOW:
        raise ValueError("discovery window cannot exceed 7 days")
    if not 1 <= query.limit <= MAX_RESULTS:
        raise ValueError(f"limit must be between 1 and {MAX_RESULTS}")
