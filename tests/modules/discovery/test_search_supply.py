from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from request_engine.modules.booking.contracts.appointments import AppointmentSlot, ResourceChoice
from request_engine.modules.booking.contracts.discovery import PublishedSlotQuery
from request_engine.modules.discovery.application.queries.search_supply import (
    DiscoveryCandidate,
    SearchPublishedSupplyQuery,
    search_published_supply,
)

NOW = datetime(2035, 1, 1, 12, tzinfo=UTC)


class Candidates:
    def __init__(self, values: tuple[DiscoveryCandidate, ...]) -> None:
        self.values = values

    async def find_candidates(
        self, query: SearchPublishedSupplyQuery, *, scan_limit: int
    ) -> tuple[DiscoveryCandidate, ...]:
        del query, scan_limit
        return self.values


class Slots:
    def __init__(self, values: dict[UUID, tuple[AppointmentSlot, ...]]) -> None:
        self.values = values
        self.queries: list[PublishedSlotQuery] = []
        self.batch_calls = 0

    async def find_published_slots(self, query: PublishedSlotQuery) -> tuple[AppointmentSlot, ...]:
        self.queries.append(query)
        return self.values.get(query.organization_id, ())

    async def find_published_slots_batch(
        self, queries: tuple[PublishedSlotQuery, ...]
    ) -> tuple[tuple[AppointmentSlot, ...], ...]:
        self.batch_calls += 1
        self.queries.extend(queries)
        return tuple(self.values.get(query.organization_id, ()) for query in queries)


def candidate(distance: float, *, publication_end: datetime | None = None) -> DiscoveryCandidate:
    return DiscoveryCandidate(
        publication_id=uuid4(),
        publication_revision=1,
        mapping_id=uuid4(),
        mapping_revision=2,
        organization_id=uuid4(),
        organization_key="org",
        organization_display_name="Org",
        offering_id=uuid4(),
        offering_key="cardio",
        offering_display_name="Cardiology",
        offering_version_id=uuid4(),
        location_id=uuid4(),
        location_key="clinic",
        location_display_name="Clinic",
        resource_id=None,
        provider_visibility="hidden",
        publication_start=NOW - timedelta(days=1),
        publication_end=publication_end,
        distance_meters=distance,
    )


def contextual_slot(item: DiscoveryCandidate, start: datetime) -> AppointmentSlot:
    return AppointmentSlot(
        offering_version_id=item.offering_version_id,
        start_at=start,
        end_at=start + timedelta(minutes=30),
        location_id=item.location_id,
        resources=(ResourceChoice(uuid4(), uuid4(), uuid4(), 1, 1),),
        planned_duration_minutes=30,
        amount=Decimal("3500"),
        currency="DOP",
        location_operational_revision=1,
        configuration_fingerprint="sha256:test",
    )


def search_query() -> SearchPublishedSupplyQuery:
    return SearchPublishedSupplyQuery(
        "cardiology",
        Decimal("19.8"),
        Decimal("-70.7"),
        10_000,
        NOW,
        NOW + timedelta(days=1),
        10,
    )


@pytest.mark.asyncio
async def test_search_orders_by_time_then_distance_and_batches_observations() -> None:
    near, far = candidate(100.0), candidate(900.0)
    same_start = NOW + timedelta(hours=1)
    slots = Slots(
        {
            far.organization_id: (contextual_slot(far, same_start),),
            near.organization_id: (contextual_slot(near, same_start),),
        }
    )
    result = await search_published_supply(Candidates((far, near)), slots, search_query())
    assert [item.candidate.distance_meters for item in result] == [100.0, 900.0]
    assert slots.batch_calls == 1
    observed = {query.organization_id: query for query in slots.queries}
    assert observed[near.organization_id].publication_id == near.publication_id
    assert observed[near.organization_id].mapping_id == near.mapping_id
    assert observed[near.organization_id].mapping_revision == near.mapping_revision


@pytest.mark.asyncio
async def test_search_clips_availability_to_publication_window() -> None:
    item = candidate(100.0, publication_end=NOW + timedelta(minutes=20))
    slots = Slots({item.organization_id: ()})
    assert await search_published_supply(Candidates((item,)), slots, search_query()) == ()
    assert slots.batch_calls == 1
    assert slots.queries[0].window_end == NOW + timedelta(minutes=20)


@pytest.mark.asyncio
async def test_search_excludes_slot_without_resource_assignment_provenance() -> None:
    item = candidate(100.0)
    incomplete = contextual_slot(item, NOW + timedelta(hours=1))
    incomplete = AppointmentSlot(
        offering_version_id=incomplete.offering_version_id,
        start_at=incomplete.start_at,
        end_at=incomplete.end_at,
        location_id=incomplete.location_id,
        resources=(ResourceChoice(uuid4(), uuid4(), availability_revision=1),),
        planned_duration_minutes=incomplete.planned_duration_minutes,
        amount=incomplete.amount,
        currency=incomplete.currency,
        location_operational_revision=incomplete.location_operational_revision,
        configuration_fingerprint=incomplete.configuration_fingerprint,
    )
    result = await search_published_supply(
        Candidates((item,)), Slots({item.organization_id: (incomplete,)}), search_query()
    )
    assert result == ()
