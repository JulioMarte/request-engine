from uuid import UUID

import pytest

from request_engine.modules.live_capacity.contracts.projection import (
    EstimateSource,
    ProjectionWorkItem,
)
from request_engine.modules.live_capacity.domain.deduplication import deduplicate_remaining_work

pytestmark = [pytest.mark.unit, pytest.mark.invariant]


def _id(value: int) -> UUID:
    return UUID(int=value)


def _work(
    key: int,
    *,
    queue_entry: int | None = None,
    reservation: int | None = None,
) -> ProjectionWorkItem:
    return ProjectionWorkItem(
        key=_id(key),
        duration_seconds=1200,
        source=EstimateSource.CONFIGURED_POLICY,
        queue_entry_id=_id(queue_entry) if queue_entry is not None else None,
        reservation_id=_id(reservation) if reservation is not None else None,
    )


def test_live_queue_representation_supersedes_same_reservation() -> None:
    planned = (_work(1, reservation=10),)
    queued = (_work(2, queue_entry=20, reservation=10),)

    result = deduplicate_remaining_work(planned=planned, queued=queued, active=())

    assert tuple(item.key for item in result) == (_id(2),)


def test_active_session_supersedes_queue_entry_and_reservation() -> None:
    planned = (_work(1, reservation=10),)
    queued = (_work(2, queue_entry=20, reservation=10),)
    active = (_work(3, queue_entry=20, reservation=10),)

    result = deduplicate_remaining_work(planned=planned, queued=queued, active=active)

    assert tuple(item.key for item in result) == (_id(3),)


def test_walk_in_is_kept_without_reservation() -> None:
    walk_in = _work(4, queue_entry=40)

    result = deduplicate_remaining_work(planned=(), queued=(walk_in,), active=())

    assert result == (walk_in,)
