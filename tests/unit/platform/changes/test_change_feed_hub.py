"""Fan-out, slow-consumer and cursor semantics of the in-memory change hub.

Protected risks: a slow stream blocking or growing without bound (it must be
cut to one ``reset``), events leaking across organizations or topics, a
principal exceeding its concurrent stream budget, and a batch cursor that
would let a reconnecting client skip a fact it never received.
"""

from asyncio import Queue
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from request_engine.platform.changes.hub import ChangeHub, StreamLimitExceeded
from request_engine.platform.changes.model import (
    ChangeEvent,
    ChangeItem,
    FeedSnapshot,
    ResetItem,
    StreamItem,
    parse_cursor,
)

pytestmark = [pytest.mark.unit]

_T0 = datetime(2026, 10, 22, 14, 3, 11, 204_000, tzinfo=UTC)


def _snapshot(xmin: int, xmax: int, *, seconds: int = 0) -> FeedSnapshot:
    return FeedSnapshot(snapshot=f"{xmin}:{xmax}:", taken_at=_T0 + timedelta(seconds=seconds))


def _event(topic: str, resource_id: UUID | None = None) -> ChangeEvent:
    return ChangeEvent(
        topic=topic,
        kind="reservation.checked_in.v1",
        resource_type="reservation",
        resource_id=resource_id or uuid4(),
        queue_id=None,
        location_id=None,
        business_date=date(2026, 10, 22),
        occurred_at=_T0,
    )


def _drain(queue_items: Queue[StreamItem]) -> list[StreamItem]:
    drained: list[StreamItem] = []
    while not queue_items.empty():
        drained.append(queue_items.get_nowait())
    return drained


def test_slow_consumer_is_cut_to_a_single_reset_without_blocking_others() -> None:
    hub = ChangeHub(max_streams_per_principal=5, queue_size=3)
    org = uuid4()
    slow = hub.subscribe(
        organization_id=org,
        principal_id=uuid4(),
        topics=frozenset({"day_board"}),
        baseline=_snapshot(10, 10),
    )
    fast = hub.subscribe(
        organization_id=org,
        principal_id=uuid4(),
        topics=frozenset({"day_board"}),
        baseline=_snapshot(10, 10),
    )
    for step in range(5):
        hub.deliver(
            org,
            [_event("day_board")],
            previous=_snapshot(10 + step, 10 + step),
            current=_snapshot(11 + step, 11 + step),
        )
        if step < 4:
            # The fast consumer keeps up; the slow one never reads.
            assert isinstance(fast.queue.get_nowait(), ChangeItem)

    slow_items = _drain(slow.queue)
    # 3 queued, the 4th overflowed -> [reset], then the 5th was appended after it.
    assert isinstance(slow_items[0], ResetItem)
    assert sum(isinstance(item, ResetItem) for item in slow_items) == 1
    assert len(slow_items) <= 3
    assert slow.resets == 1
    assert [type(item) for item in _drain(fast.queue)] == [ChangeItem]


def test_delivery_is_filtered_by_organization_and_topic() -> None:
    hub = ChangeHub(max_streams_per_principal=5, queue_size=10)
    org_a, org_b = uuid4(), uuid4()
    board = hub.subscribe(
        organization_id=org_a,
        principal_id=uuid4(),
        topics=frozenset({"day_board"}),
        baseline=_snapshot(1, 1),
    )
    queue = hub.subscribe(
        organization_id=org_a,
        principal_id=uuid4(),
        topics=frozenset({"queue"}),
        baseline=_snapshot(1, 1),
    )
    foreign = hub.subscribe(
        organization_id=org_b,
        principal_id=uuid4(),
        topics=frozenset({"day_board", "queue"}),
        baseline=_snapshot(1, 1),
    )
    shown = uuid4()
    hub.deliver(
        org_a,
        [_event("day_board", shown)],
        previous=_snapshot(1, 1),
        current=_snapshot(2, 2),
    )
    items = _drain(board.queue)
    assert len(items) == 1 and isinstance(items[0], ChangeItem)
    assert items[0].event.resource_id == shown
    assert _drain(queue.queue) == []
    assert _drain(foreign.queue) == []


def test_only_the_last_item_of_a_batch_advances_the_cursor() -> None:
    hub = ChangeHub(max_streams_per_principal=5, queue_size=10)
    org = uuid4()
    stream = hub.subscribe(
        organization_id=org,
        principal_id=uuid4(),
        topics=frozenset({"day_board"}),
        baseline=_snapshot(5, 5),
    )
    previous, current = _snapshot(5, 7, seconds=1), _snapshot(9, 9, seconds=2)
    hub.deliver(
        org,
        [_event("day_board"), _event("queue"), _event("day_board")],
        previous=previous,
        current=current,
    )
    items = _drain(stream.queue)
    assert all(isinstance(item, ChangeItem) for item in items)
    cursors = [item.cursor for item in items if isinstance(item, ChangeItem)]
    # A client cut off after the first item must replay from `previous`,
    # which still includes the second (undelivered) fact.
    assert [parse_cursor(cursor) for cursor in cursors] == [previous, current]


def test_per_principal_limit_is_enforced_and_released() -> None:
    hub = ChangeHub(max_streams_per_principal=2, queue_size=4)
    org, principal = uuid4(), uuid4()
    first = hub.subscribe(
        organization_id=org,
        principal_id=principal,
        topics=frozenset({"queue"}),
        baseline=_snapshot(1, 1),
    )
    hub.subscribe(
        organization_id=org,
        principal_id=principal,
        topics=frozenset({"queue"}),
        baseline=_snapshot(1, 1),
    )
    with pytest.raises(StreamLimitExceeded):
        hub.subscribe(
            organization_id=org,
            principal_id=principal,
            topics=frozenset({"queue"}),
            baseline=_snapshot(1, 1),
        )
    # Another principal is unaffected.
    hub.subscribe(
        organization_id=org,
        principal_id=uuid4(),
        topics=frozenset({"queue"}),
        baseline=_snapshot(1, 1),
    )
    hub.unsubscribe(first)
    hub.unsubscribe(first)  # idempotent: never double-releases a slot
    assert hub.stream_count(principal) == 1
    hub.subscribe(
        organization_id=org,
        principal_id=principal,
        topics=frozenset({"queue"}),
        baseline=_snapshot(1, 1),
    )
    assert hub.stream_count(principal) == 2


def test_last_unsubscribe_forgets_the_organization_baseline() -> None:
    hub = ChangeHub(max_streams_per_principal=2, queue_size=4)
    org = uuid4()
    stream = hub.subscribe(
        organization_id=org,
        principal_id=uuid4(),
        topics=frozenset({"queue"}),
        baseline=_snapshot(3, 3),
    )
    assert hub.baselines[org] == _snapshot(3, 3)
    hub.unsubscribe(stream)
    assert not hub.tracked(org) and org not in hub.baselines


@pytest.mark.parametrize(
    "value",
    ["", "garbage", "2.1.MTox", "1.x.MTox", "1.1.!!!", "1.1." + "A" * 5000, "1.1.MTp4Og"],
)
def test_unknown_cursors_are_rejected(value: str) -> None:
    assert parse_cursor(value) is None


def test_cursor_round_trips_snapshot_and_issue_instant() -> None:
    snapshot = FeedSnapshot(snapshot="100:105:101,103", taken_at=_T0)
    assert parse_cursor(snapshot.cursor()) == snapshot


def test_change_data_has_exactly_the_contract_fields() -> None:
    resource = UUID("0190f000-0000-7000-8000-000000000001")
    event = ChangeEvent(
        topic="day_board",
        kind="reservation.checked_in.v1",
        resource_type="reservation",
        resource_id=resource,
        queue_id=None,
        location_id=UUID("0190f000-0000-7000-8000-000000000002"),
        business_date=date(2026, 10, 22),
        occurred_at=_T0,
    )
    assert event.data() == {
        "topic": "day_board",
        "kind": "reservation.checked_in.v1",
        "resource_type": "reservation",
        "resource_id": str(resource),
        "scope": {
            "queue_id": None,
            "location_id": "0190f000-0000-7000-8000-000000000002",
            "business_date": "2026-10-22",
        },
        "occurred_at": "2026-10-22T14:03:11.204Z",
    }
