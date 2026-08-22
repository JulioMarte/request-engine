from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from request_engine.modules.booking.contracts.appointments import AppointmentSlot
from request_engine.modules.booking.contracts.discovery import PublishedSlotQuery
from request_engine.modules.discovery.application.queries.search_supply import (
    DiscoveryCandidate,
    SearchPublishedSupplyQuery,
    search_published_supply,
    validate_search_query,
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

    async def find_published_slots(
        self, query: PublishedSlotQuery
    ) -> tuple[AppointmentSlot, ...]:
        return self.values.get(query.organization_id, ())


def candidate(distance: float, *, publication_end: datetime | None = None) -> DiscoveryCandidate:
    return DiscoveryCandidate(
        publication_id=uuid4(),
        publication_revision=1,
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


def slot(item: DiscoveryCandidate, start: datetime) -> AppointmentSlot:
    return AppointmentSlot(
        offering_version_id=item.offering_version_id,
        start_at=start,
        end_at=start + timedelta(minutes=30),
        location_id=item.location_id,
        resources=(),
    )


def query(**changes: object) -> SearchPublishedSupplyQuery:
    values: dict[str, object] = {
        "service_classification_key": "cardiology",
        "origin_latitude": Decimal("19.8"),
        "origin_longitude": Decimal("-70.7"),
        "radius_meters": 10_000,
        "window_start": NOW,
        "window_end": NOW + timedelta(days=1),
        "limit": 10,
    }
    values.update(changes)
    return SearchPublishedSupplyQuery(**values)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_search_orders_by_time_then_distance() -> None:
    near = candidate(100.0)
    far = candidate(900.0)
    same_start = NOW + timedelta(hours=1)
    slots = {
        far.organization_id: (slot(far, same_start),),
        near.organization_id: (slot(near, same_start),),
    }
    result = await search_published_supply(Candidates((far, near)), Slots(slots), query())
    assert [item.candidate.distance_meters for item in result] == [100.0, 900.0]


@pytest.mark.asyncio
async def test_search_clips_slots_to_publication_window() -> None:
    item = candidate(100.0, publication_end=NOW + timedelta(minutes=20))
    reader = Slots({item.organization_id: ()})
    assert await search_published_supply(Candidates((item,)), reader, query()) == ()


@pytest.mark.parametrize(
    "changes",
    [
        {"origin_latitude": Decimal("91")},
        {"origin_longitude": Decimal("181")},
        {"radius_meters": 0},
        {"radius_meters": 100_001},
        {"limit": 101},
        {"window_end": NOW + timedelta(days=8)},
        {"window_end": NOW},
    ],
)
def test_search_validation_rejects_unbounded_inputs(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        validate_search_query(query(**changes))
