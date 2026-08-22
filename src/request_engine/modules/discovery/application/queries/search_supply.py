from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from request_engine.modules.booking.contracts.appointments import AppointmentSlot
from request_engine.modules.booking.contracts.discovery import PublishedSlotQuery, PublishedSlotReader

MAX_RADIUS_METERS = 100_000
MAX_WINDOW = timedelta(days=7)
MAX_RESULTS = 100
MAX_CANDIDATE_SCAN = 500


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


class DiscoveryCandidateReader(Protocol):
    async def find_candidates(
        self,
        query: SearchPublishedSupplyQuery,
        *,
        scan_limit: int,
    ) -> tuple[DiscoveryCandidate, ...]: ...


async def search_published_supply(
    candidate_reader: DiscoveryCandidateReader,
    slot_reader: PublishedSlotReader,
    query: SearchPublishedSupplyQuery,
) -> tuple[DiscoveryOption, ...]:
    validate_search_query(query)
    candidates = await candidate_reader.find_candidates(
        query,
        scan_limit=min(MAX_CANDIDATE_SCAN, max(query.limit * 10, query.limit)),
    )
    options: list[DiscoveryOption] = []
    for candidate in candidates:
        start = max(query.window_start, candidate.publication_start)
        end = query.window_end
        if candidate.publication_end is not None:
            end = min(end, candidate.publication_end)
        if end <= start:
            continue
        slots = await slot_reader.find_published_slots(
            PublishedSlotQuery(
                organization_id=candidate.organization_id,
                offering_version_id=candidate.offering_version_id,
                window_start=start,
                window_end=end,
                location_id=candidate.location_id,
                resource_id=candidate.resource_id,
                limit=query.limit,
            )
        )
        options.extend(DiscoveryOption(candidate, slot) for slot in slots)
    options.sort(
        key=lambda item: (
            item.slot.start_at,
            item.candidate.distance_meters,
            str(item.candidate.organization_id),
            str(item.candidate.location_id),
            str(item.candidate.offering_id),
            str(item.candidate.publication_id),
        )
    )
    return tuple(options[: query.limit])


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
