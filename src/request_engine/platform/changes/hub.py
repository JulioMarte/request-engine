"""In-memory fan-out of committed change events to bounded per-stream queues."""

import asyncio
from collections import defaultdict
from collections.abc import Sequence
from uuid import UUID

from request_engine.platform.changes.model import (
    ChangeEvent,
    ChangeItem,
    FeedSnapshot,
    ResetItem,
    StreamItem,
)


class StreamLimitExceeded(Exception):
    """The principal already holds the configured number of concurrent streams."""


class Subscription:
    """One open stream: an organization, its authorized topics and a bounded queue."""

    def __init__(
        self,
        *,
        organization_id: UUID,
        principal_id: UUID,
        topics: frozenset[str],
        queue_size: int,
    ) -> None:
        self.organization_id = organization_id
        self.principal_id = principal_id
        self.topics = topics
        self.queue: asyncio.Queue[StreamItem] = asyncio.Queue(maxsize=queue_size)
        self.resets = 0

    def offer(self, items: Sequence[StreamItem]) -> None:
        """Enqueue without ever blocking the shared fan-out.

        A slow consumer whose queue is full loses its pending items and receives
        one ``reset`` instead: the client then refetches everything it shows,
        which is always correct for an invalidation-only feed.
        """

        for item in items:
            try:
                self.queue.put_nowait(item)
            except asyncio.QueueFull:
                while not self.queue.empty():
                    self.queue.get_nowait()
                self.queue.put_nowait(ResetItem())
                self.resets += 1
                return


class ChangeHub:
    """Organization/topic-filtered fan-out plus per-principal stream admission."""

    def __init__(self, *, max_streams_per_principal: int, queue_size: int) -> None:
        if max_streams_per_principal < 1:
            raise ValueError("max_streams_per_principal must be positive")
        if queue_size < 2:
            raise ValueError("subscriber queue must hold at least two items")
        self._max_per_principal = max_streams_per_principal
        self._queue_size = queue_size
        self._by_org: dict[UUID, set[Subscription]] = defaultdict(set)
        self._per_principal: dict[UUID, int] = defaultdict(int)
        self.baselines: dict[UUID, FeedSnapshot] = {}

    def subscribe(
        self,
        *,
        organization_id: UUID,
        principal_id: UUID,
        topics: frozenset[str],
        baseline: FeedSnapshot,
    ) -> Subscription:
        if self._per_principal[principal_id] >= self._max_per_principal:
            raise StreamLimitExceeded
        subscription = Subscription(
            organization_id=organization_id,
            principal_id=principal_id,
            topics=topics,
            queue_size=self._queue_size,
        )
        self._per_principal[principal_id] += 1
        self._by_org[organization_id].add(subscription)
        # A newly tracked organization starts reading after a snapshot taken
        # before this subscription; earlier facts are covered by replay.
        self.baselines.setdefault(organization_id, baseline)
        return subscription

    def unsubscribe(self, subscription: Subscription) -> None:
        subscribers = self._by_org.get(subscription.organization_id)
        if subscribers is None or subscription not in subscribers:
            return
        subscribers.discard(subscription)
        self._per_principal[subscription.principal_id] -= 1
        if self._per_principal[subscription.principal_id] <= 0:
            del self._per_principal[subscription.principal_id]
        if not subscribers:
            del self._by_org[subscription.organization_id]
            self.baselines.pop(subscription.organization_id, None)

    def tracked(self, organization_id: UUID) -> bool:
        return organization_id in self._by_org

    def tracked_organizations(self) -> tuple[UUID, ...]:
        return tuple(self._by_org)

    def stream_count(self, principal_id: UUID | None = None) -> int:
        if principal_id is not None:
            return self._per_principal.get(principal_id, 0)
        return sum(len(items) for items in self._by_org.values())

    def deliver(
        self,
        organization_id: UUID,
        events: Sequence[ChangeEvent],
        *,
        previous: FeedSnapshot,
        current: FeedSnapshot,
    ) -> None:
        """Fan one committed batch out in order.

        Every item carries ``previous``'s cursor except a subscriber's last item of
        the batch, which carries ``current``'s: only once that item is received has
        the client seen everything committed before ``current``. Replaying from any
        delivered cursor therefore never skips a fact (it may repeat some).
        """

        previous_cursor = previous.cursor()
        current_cursor = current.cursor()
        for subscription in tuple(self._by_org.get(organization_id, ())):
            selected = [event for event in events if event.topic in subscription.topics]
            if not selected:
                continue
            items: list[StreamItem] = [
                ChangeItem(event=event, cursor=previous_cursor) for event in selected[:-1]
            ]
            items.append(ChangeItem(event=selected[-1], cursor=current_cursor))
            subscription.offer(items)

    def reset(self, organization_id: UUID) -> None:
        for subscription in tuple(self._by_org.get(organization_id, ())):
            subscription.offer((ResetItem(),))
