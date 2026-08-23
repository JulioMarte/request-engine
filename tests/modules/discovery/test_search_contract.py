from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from request_engine.modules.discovery.application.errors import (
    DiscoverySearchContractError,
    DiscoverySearchTooBroad,
)
from request_engine.modules.discovery.application.queries.search_supply import (
    DiscoveryCandidate,
    SearchPublishedSupplyQuery,
    search_published_supply,
)
from request_engine.modules.discovery.application.search_contract import (
    MAX_ELIGIBLE_CANDIDATES,
    validate_search_query,
)

NOW = datetime(2035, 1, 1, 12, tzinfo=UTC)


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


@pytest.mark.parametrize(
    "changes",
    [
        {"service_classification_key": "Cardiology"},
        {"service_classification_key": "cardiology "},
        {"origin_latitude": Decimal("91")},
        {"origin_longitude": Decimal("181")},
        {"radius_meters": 0},
        {"radius_meters": 100_001},
        {"limit": 101},
        {"window_end": NOW + timedelta(days=8)},
        {"window_end": NOW},
        {"window_start": datetime(2035, 1, 1, 12), "window_end": datetime(2035, 1, 2, 12)},
    ],
)
def test_search_validation_rejects_noncanonical_or_unbounded_inputs(
    changes: dict[str, object],
) -> None:
    with pytest.raises(DiscoverySearchContractError):
        validate_search_query(query(**changes))


class TooManyCandidates:
    async def find_candidates(
        self,
        request: SearchPublishedSupplyQuery,
        *,
        scan_limit: int,
    ) -> tuple[DiscoveryCandidate, ...]:
        del request
        assert scan_limit == MAX_ELIGIBLE_CANDIDATES + 1
        marker = object()
        return (marker,) * scan_limit  # type: ignore[return-value]


class SlotsMustNotRun:
    async def find_published_slots(self, query: object) -> tuple[object, ...]:
        del query
        raise AssertionError("slot evaluation must not run for an incomplete candidate set")


@pytest.mark.asyncio
async def test_search_rejects_candidate_overflow_instead_of_truncating_ranking() -> None:
    with pytest.raises(DiscoverySearchTooBroad):
        await search_published_supply(TooManyCandidates(), SlotsMustNotRun(), query())  # type: ignore[arg-type]
