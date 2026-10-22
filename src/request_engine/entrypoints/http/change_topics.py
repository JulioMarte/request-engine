"""The single routing table of the change feed: outbox facts -> topics (ADR 0020).

A topic is an invalidation channel for what a client may be displaying. It is
authorized by an existing owner read capability; it creates no new authority
and carries no owner data. Facts keep their owners (booking, queue, delivery,
requests); this table only decides which already-authorized read a fact may
make stale.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from request_engine.platform.changes.model import ChangeEvent, FeedRow

TOPIC_CAPABILITIES: Mapping[str, str] = MappingProxyType(
    {
        "day_board": "appointments.day_board",
        "queue": "queue.staff_read",
        "requests": "requests.read_inbox",
    }
)


@dataclass(frozen=True, slots=True)
class _Route:
    event_prefix: str
    aggregate_kind: str
    resource_type: str
    topics: tuple[str, ...]
    day_board_when_reserved: bool = False


_ROUTES: tuple[_Route, ...] = (
    _Route("reservation.", "Reservation", "reservation", ("day_board",)),
    _Route("service_session.", "ServiceSession", "service_session", ("day_board", "queue")),
    _Route("queue.", "QueueEntry", "queue_entry", ("queue",), day_board_when_reserved=True),
    _Route("request.", "Request", "request", ("requests",)),
)

# A reschedule changes two business dates (old and new); leave it unnarrowed.
_UNNARROWED_BUSINESS_DATE = frozenset({"reservation.rescheduled.v1"})


def _like_prefix(prefix: str) -> str:
    escaped = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return escaped + "%"


class ChangeTopicTable:
    """Implements the feed's ``ChangeTopicCatalog`` from the routes above."""

    @property
    def topics(self) -> frozenset[str]:
        return frozenset(TOPIC_CAPABILITIES)

    def patterns(self, topics: frozenset[str]) -> tuple[str, ...]:
        selected: list[str] = []
        for route in _ROUTES:
            route_topics = set(route.topics)
            if route.day_board_when_reserved:
                route_topics.add("day_board")
            if route_topics & topics:
                selected.append(_like_prefix(route.event_prefix))
        return tuple(selected)

    def events_for(self, row: FeedRow) -> tuple[ChangeEvent, ...]:
        route = next(
            (item for item in _ROUTES if row.event_type.startswith(item.event_prefix)), None
        )
        if route is None or row.aggregate_kind != route.aggregate_kind:
            return ()
        if row.aggregate_id is None:
            return ()
        topics = list(route.topics)
        if route.day_board_when_reserved and row.reservation_id is not None:
            topics.insert(0, "day_board")
        business_date = None if row.event_type in _UNNARROWED_BUSINESS_DATE else row.business_date
        return tuple(
            ChangeEvent(
                topic=topic,
                kind=row.event_type,
                resource_type=route.resource_type,
                resource_id=row.aggregate_id,
                queue_id=row.queue_id,
                location_id=row.location_id,
                business_date=business_date,
                occurred_at=row.occurred_at,
            )
            for topic in topics
        )
