"""The single change-feed routing table: facts -> topics, never more data.

Protected risks: a fact routed to a topic whose capability does not authorize
reading it (e.g. a Request on ``day_board``), an unreserved walk-in QueueEntry
invalidating the appointments board, a reschedule narrowed to only one of the
two dates it changes, an aggregate/prefix mismatch producing a bogus resource,
SQL LIKE wildcards in event prefixes over-selecting, and the feed delivering a
batch in creation order instead of notification (commit) order.
"""

from collections.abc import Sequence
from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest

from request_engine.entrypoints.http.change_topics import TOPIC_CAPABILITIES, ChangeTopicTable
from request_engine.platform.changes.feed import ChangeFeed
from request_engine.platform.changes.model import ChangeItem, FeedRow, FeedSnapshot
from request_engine.platform.changes.postgres import FeedDelta

pytestmark = [pytest.mark.unit]

_AT = datetime(2026, 10, 22, 14, 0, tzinfo=UTC)
_TABLE = ChangeTopicTable()


def _row(
    event_type: str,
    aggregate_kind: str | None,
    *,
    reservation_id: UUID | None = None,
    xid: int = 100,
    event_id: UUID | None = None,
) -> FeedRow:
    return FeedRow(
        event_id=event_id or uuid4(),
        event_type=event_type,
        aggregate_kind=aggregate_kind,
        aggregate_id=uuid4(),
        change_xid=xid,
        occurred_at=_AT,
        queue_id=uuid4() if aggregate_kind in {"QueueEntry", "ServiceSession"} else None,
        location_id=uuid4(),
        business_date=date(2026, 10, 22),
        reservation_id=reservation_id,
    )


def test_topics_are_authorized_by_existing_owner_read_capabilities() -> None:
    assert dict(TOPIC_CAPABILITIES) == {
        "day_board": "appointments.day_board",
        "queue": "queue.staff_read",
        "requests": "requests.read_inbox",
    }


@pytest.mark.parametrize(
    ("event_type", "kind", "reserved", "topics", "resource_type"),
    [
        ("reservation.created.v1", "Reservation", True, ["day_board"], "reservation"),
        ("reservation.checked_in.v1", "Reservation", True, ["day_board"], "reservation"),
        ("reservation.cancelled.v1", "Reservation", True, ["day_board"], "reservation"),
        ("reservation.no_show_recorded.v1", "Reservation", True, ["day_board"], "reservation"),
        (
            "service_session.started.v1",
            "ServiceSession",
            False,
            ["day_board", "queue"],
            "service_session",
        ),
        (
            "service_session.completed.v1",
            "ServiceSession",
            True,
            ["day_board", "queue"],
            "service_session",
        ),
        ("queue.entry_called.v1", "QueueEntry", True, ["day_board", "queue"], "queue_entry"),
        ("queue.entry_checked_in.v1", "QueueEntry", False, ["queue"], "queue_entry"),
        ("queue.entry_cancelled.v1", "QueueEntry", False, ["queue"], "queue_entry"),
        ("queue.entry_joined.v1", "QueueEntry", False, ["queue"], "queue_entry"),
        ("queue.entry_joined.v1", "QueueEntry", True, ["day_board", "queue"], "queue_entry"),
        ("queue.entry_skipped.v1", "QueueEntry", True, ["day_board", "queue"], "queue_entry"),
        ("queue.entry_recall_held.v1", "QueueEntry", True, ["day_board", "queue"], "queue_entry"),
        (
            "queue.entry_recall_released.v1",
            "QueueEntry",
            False,
            ["queue"],
            "queue_entry",
        ),
        ("request.created.v1", "Request", False, ["requests"], "request"),
        ("request.completed.v1", "Request", False, ["requests"], "request"),
    ],
)
def test_routing_table_matches_the_contract(
    event_type: str, kind: str, reserved: bool, topics: list[str], resource_type: str
) -> None:
    row = _row(event_type, kind, reservation_id=uuid4() if reserved else None)
    events = _TABLE.events_for(row)
    assert [event.topic for event in events] == topics
    assert {event.resource_type for event in events} == {resource_type}
    assert {event.resource_id for event in events} == {row.aggregate_id}
    assert {event.kind for event in events} == {event_type}


@pytest.mark.parametrize(
    ("event_type", "kind"),
    [
        ("communication.task_created.v1", "CommunicationTask"),
        ("waitlist.entry_joined.v1", "WaitlistEntry"),
        ("party.registered.v1", "Party"),
        ("workload.classification_created.v1", "OperationalWorkloadClassification"),
        # Prefix matches but the aggregate does not: never fabricate a resource.
        ("reservation.created.v1", "QueueEntry"),
        ("queue.entry_called.v1", None),
        # "requests" must not be read as the "request." family.
        ("requests.anything.v1", "Request"),
    ],
)
def test_unrouted_facts_produce_no_event(event_type: str, kind: str | None) -> None:
    assert _TABLE.events_for(_row(event_type, kind)) == ()


def test_reschedule_does_not_narrow_the_business_date() -> None:
    (event,) = _TABLE.events_for(_row("reservation.rescheduled.v1", "Reservation"))
    assert event.business_date is None
    (created,) = _TABLE.events_for(_row("reservation.created.v1", "Reservation"))
    assert created.business_date == date(2026, 10, 22)


def test_like_patterns_escape_wildcards_and_follow_topic_selection() -> None:
    assert _TABLE.patterns(frozenset({"requests"})) == ("request.%",)
    assert _TABLE.patterns(frozenset({"queue"})) == ("service\\_session.%", "queue.%")
    assert set(_TABLE.patterns(frozenset({"day_board"}))) == {
        "reservation.%",
        "service\\_session.%",
        "queue.%",
    }


class _OneDeltaReader:
    def __init__(self, delta: FeedDelta) -> None:
        self.delta = delta
        self.after: list[FeedSnapshot] = []

    async def current_snapshot(self, organization_id: UUID) -> FeedSnapshot:
        del organization_id
        return FeedSnapshot(snapshot="90:90:", taken_at=_AT)

    async def read_since(
        self,
        organization_id: UUID,
        after: FeedSnapshot,
        *,
        patterns: Sequence[str],
        limit: int,
    ) -> FeedDelta:
        del organization_id, patterns, limit
        self.after.append(after)
        return self.delta


@pytest.mark.asyncio
async def test_batch_is_delivered_in_notification_commit_order_not_creation_order() -> None:
    org = uuid4()
    # xid 120 created its fact first but committed after xid 130.
    early_created = _row("reservation.created.v1", "Reservation", xid=120)
    later_created = _row("reservation.cancelled.v1", "Reservation", xid=130)
    current = FeedSnapshot(snapshot="140:140:", taken_at=_AT)
    reader = _OneDeltaReader(FeedDelta(rows=(early_created, later_created), snapshot=current))
    feed = ChangeFeed(reader=reader, catalog=_TABLE, dsn="")
    stream = await feed.subscribe(
        organization_id=org, principal_id=uuid4(), topics=frozenset({"day_board"})
    )
    feed.signal(org, 130)
    feed.signal(org, 120)
    await feed.read_and_deliver(org)

    delivered = [stream.queue.get_nowait() for _ in range(stream.queue.qsize())]
    assert [item.event.kind for item in delivered if isinstance(item, ChangeItem)] == [
        "reservation.cancelled.v1",
        "reservation.created.v1",
    ]
    assert reader.after == [FeedSnapshot(snapshot="90:90:", taken_at=_AT)]
    # The organization now reads after the delivered snapshot.
    assert feed.hub.baselines[org] == current
