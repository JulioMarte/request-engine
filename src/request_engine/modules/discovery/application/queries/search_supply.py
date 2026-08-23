from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from request_engine.modules.booking.contracts.appointments import AppointmentSlot
from request_engine.modules.booking.contracts.discovery import (
    PublishedSlotQuery,
    PublishedSlotReader,
)
from request_engine.modules.discovery.application.errors import DiscoverySearchTooBroad
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
        scan_limit=MAX_ELIGIBLE_CANDIDATES + 1,
    )
    if len(candidates) > MAX_ELIGIBLE_CANDIDATES:
        raise DiscoverySearchTooBroad(
            "discovery search matched too many published candidates; narrow the radius or window"
        )

    options: list[DiscoveryOption] = []
    for candidate in candidates:
        start = max(query.window_start, candidate.publication_start)
        end = min(
            query.window_end,
            candidate.publication_end or query.window_end,
        )
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
            DiscoveryOption(candidate, slot) for slot in slots if _is_f2_discoverable(slot)
        )

    options.sort(key=_option_order)
    return tuple(options[: query.limit])


def _is_f2_discoverable(slot: AppointmentSlot) -> bool:
    return (
        slot.location_id is not None
        and slot.configuration_fingerprint is not None
        and slot.planned_duration_minutes is not None
        and slot.amount is not None
        and slot.currency is not None
    )


def _option_order(item: DiscoveryOption) -> tuple[object, ...]:
    resource_ids = tuple(str(choice.resource_id) for choice in item.slot.resources)
    return (
        item.slot.start_at,
        item.candidate.distance_meters,
        str(item.candidate.organization_id),
        str(item.candidate.location_id),
        str(item.candidate.offering_id),
        resource_ids,
        str(item.candidate.publication_id),
    )
