from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from request_engine.modules.booking.contracts.appointments import AppointmentSlot
from request_engine.modules.booking.contracts.discovery import PublishedSlotQuery, PublishedSlotReader
from request_engine.modules.discovery.application.errors import DiscoverySearchTooBroad
from request_engine.modules.discovery.application.queries.search_ordering import (
    is_f2_discoverable,
    option_order,
)
from request_engine.modules.discovery.application.search_contract import (
    MAX_ELIGIBLE_CANDIDATES,
    validate_search_query,
)


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
    mapping_id: UUID
    mapping_revision: int
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
    location_address_line1: str | None = None
    location_address_line2: str | None = None
    location_locality: str | None = None
    location_administrative_area: str | None = None
    location_postal_code: str | None = None
    location_country_code: str | None = None
    provider_key: str | None = None
    provider_display_name: str | None = None
    provider_role_label: str | None = None
    provider_profile_image_ref: str | None = None


@dataclass(frozen=True, slots=True)
class DiscoveryOption:
    candidate: DiscoveryCandidate
    slot: AppointmentSlot


class DiscoveryCandidateReader(Protocol):
    async def find_candidates(
        self, query: SearchPublishedSupplyQuery, *, scan_limit: int
    ) -> tuple[DiscoveryCandidate, ...]: ...


async def search_published_supply(
    candidate_reader: DiscoveryCandidateReader,
    slot_reader: PublishedSlotReader,
    query: SearchPublishedSupplyQuery,
) -> tuple[DiscoveryOption, ...]:
    validate_search_query(query)
    candidates = await candidate_reader.find_candidates(
        query, scan_limit=MAX_ELIGIBLE_CANDIDATES + 1
    )
    if len(candidates) > MAX_ELIGIBLE_CANDIDATES:
        raise DiscoverySearchTooBroad(
            "discovery search matched too many published candidates; narrow the radius or window"
        )

    options: list[DiscoveryOption] = []
    for candidate in candidates:
        start = max(query.window_start, candidate.publication_start)
        end = min(query.window_end, candidate.publication_end or query.window_end)
        if end <= start:
            continue
        slots = await slot_reader.find_published_slots(
            PublishedSlotQuery(
                organization_id=candidate.organization_id,
                publication_id=candidate.publication_id,
                publication_revision=candidate.publication_revision,
                mapping_id=candidate.mapping_id,
                mapping_revision=candidate.mapping_revision,
                offering_version_id=candidate.offering_version_id,
                window_start=start,
                window_end=end,
                location_id=candidate.location_id,
                resource_id=candidate.resource_id,
                limit=query.limit,
            )
        )
        options.extend(
            DiscoveryOption(candidate, slot) for slot in slots if is_f2_discoverable(slot)
        )

    options.sort(key=option_order)
    return tuple(options[: query.limit])
