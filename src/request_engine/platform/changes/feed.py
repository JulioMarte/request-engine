"""Process-wide change feed: one LISTEN, snapshot-delta reads, bounded fan-out."""

import asyncio
import contextvars
import logging
import math
import os
from collections import defaultdict
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError

from request_engine.platform.changes.hub import ChangeHub, StreamLimitExceeded, Subscription
from request_engine.platform.changes.listener import ChangeSignalListener, ListenConnect
from request_engine.platform.changes.model import (
    ChangeEvent,
    ChangeItem,
    FeedRow,
    FeedSnapshot,
    ResetItem,
    StreamItem,
    parse_cursor,
)
from request_engine.platform.changes.postgres import FeedDelta

_LOGGER = logging.getLogger(__name__)
_CLOCK_SKEW_SECONDS = 60


class ChangeTopicCatalog(Protocol):
    """Routing policy supplied by composition: which facts feed which topics."""

    @property
    def topics(self) -> frozenset[str]: ...

    def patterns(self, topics: frozenset[str]) -> tuple[str, ...]: ...

    def events_for(self, row: FeedRow) -> tuple[ChangeEvent, ...]: ...


class ChangeFeedReader(Protocol):
    async def current_snapshot(self, organization_id: UUID) -> FeedSnapshot: ...

    async def read_since(
        self,
        organization_id: UUID,
        after: FeedSnapshot,
        *,
        patterns: Sequence[str],
        limit: int,
    ) -> FeedDelta: ...


def _env_number(name: str, default: str) -> float:
    raw = os.environ.get(name, default)
    value = float(raw)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


@dataclass(frozen=True, slots=True)
class ChangeFeedSettings:
    heartbeat_seconds: float = 15.0
    authority_recheck_seconds: float = 30.0
    max_streams_per_principal: int = 5
    replay_window_seconds: float = 900.0
    replay_limit: int = 500
    batch_limit: int = 2000
    subscriber_queue_size: int = 256
    startup_wait_seconds: float = 3.0
    retry_milliseconds: int = 3000
    listen_dsn: str | None = None

    def __post_init__(self) -> None:
        if not 0 < self.heartbeat_seconds <= 15:
            raise ValueError("heartbeat must be > 0 and <= 15 seconds")
        if not 0 < self.authority_recheck_seconds <= 60:
            raise ValueError("authority re-check must be > 0 and <= 60 seconds")
        if not 1 <= self.max_streams_per_principal <= 100:
            raise ValueError("per-principal stream limit must be between 1 and 100")
        if not 0 < self.replay_window_seconds <= 86_400:
            raise ValueError("replay window must be > 0 and <= 1 day")
        if self.replay_limit < 1 or self.batch_limit < 1 or self.subscriber_queue_size < 2:
            raise ValueError("feed limits must be positive")
        if not 0 < self.startup_wait_seconds <= 30:
            raise ValueError("startup wait must be > 0 and <= 30 seconds")

    @classmethod
    def from_environment(cls) -> "ChangeFeedSettings":
        return cls(
            max_streams_per_principal=int(
                os.environ.get("REQUEST_ENGINE_CHANGE_STREAM_MAX_PER_PRINCIPAL", "5")
            ),
            replay_window_seconds=_env_number(
                "REQUEST_ENGINE_CHANGE_STREAM_REPLAY_WINDOW_SECONDS", "900"
            ),
        )


class ChangeFeedUnavailable(Exception):
    """The shared LISTEN connection is not established."""


def _snapshot_xmin(snapshot: FeedSnapshot) -> int:
    return int(snapshot.snapshot.split(":", 1)[0])


class ChangeFeed:
    """Deliver committed outbox facts to subscribed streams in commit order.

    Delivery reads, per tracked organization, every fact not visible in the last
    delivered snapshot (``request_read.change_feed_v1``). Notifications are only
    wake-ups; because they arrive in commit order they also order the facts of
    one read batch. Facts are never read while any authoritative lock is held:
    the producing transaction has committed before its notification exists.
    """

    def __init__(
        self,
        *,
        reader: ChangeFeedReader,
        catalog: ChangeTopicCatalog,
        dsn: str,
        settings: ChangeFeedSettings | None = None,
        connect: ListenConnect | None = None,
    ) -> None:
        self.settings = settings or ChangeFeedSettings()
        self._reader = reader
        self._catalog = catalog
        self.hub = ChangeHub(
            max_streams_per_principal=self.settings.max_streams_per_principal,
            queue_size=self.settings.subscriber_queue_size,
        )
        self._listener = ChangeSignalListener(
            dsn=self.settings.listen_dsn or dsn,
            on_signal=self.signal,
            on_connected=self._on_connected,
            connect=connect,
        )
        self._dirty: set[UUID] = set()
        self._wake = asyncio.Event()
        self._arrival: dict[UUID, dict[int, int]] = defaultdict(dict)
        self._arrival_counter = 0
        self._stop: asyncio.Event | None = None
        self._tasks: tuple[asyncio.Task[None], ...] = ()

    async def ensure_started(self) -> None:
        if not self._tasks:
            self._stop = asyncio.Event()
            # A clean context: the background tasks must not inherit the
            # request-bound actor that happened to trigger the lazy start.
            clean = contextvars.Context()
            self._tasks = (
                asyncio.create_task(self._listener.run(self._stop), context=clean),
                asyncio.create_task(self._process(self._stop), context=clean),
            )
        if self._listener.ready.is_set():
            return
        try:
            async with asyncio.timeout(self.settings.startup_wait_seconds):
                await self._listener.ready.wait()
        except TimeoutError as exc:
            raise ChangeFeedUnavailable from exc

    async def aclose(self) -> None:
        if self._stop is not None:
            self._stop.set()
        self._wake.set()
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with suppress(asyncio.CancelledError):
                await task
        self._tasks = ()

    def admit(self, principal_id: UUID) -> None:
        if self.hub.stream_count(principal_id) >= self.settings.max_streams_per_principal:
            raise StreamLimitExceeded

    async def subscribe(
        self, *, organization_id: UUID, principal_id: UUID, topics: frozenset[str]
    ) -> Subscription:
        self.admit(principal_id)
        baseline = await self._reader.current_snapshot(organization_id)
        return self.hub.subscribe(
            organization_id=organization_id,
            principal_id=principal_id,
            topics=topics,
            baseline=baseline,
        )

    def unsubscribe(self, subscription: Subscription) -> None:
        self.hub.unsubscribe(subscription)
        if not self.hub.tracked(subscription.organization_id):
            self._arrival.pop(subscription.organization_id, None)

    async def replay(self, subscription: Subscription, last_event_id: str) -> list[StreamItem]:
        """Facts committed after the client's cursor, read after it subscribed."""

        cursor = parse_cursor(last_event_id)
        now = datetime.now(UTC)
        if cursor is None:
            return [ResetItem()]
        age = (now - cursor.taken_at).total_seconds()
        if age > self.settings.replay_window_seconds or age < -_CLOCK_SKEW_SECONDS:
            return [ResetItem()]
        delta = await self._reader.read_since(
            subscription.organization_id,
            cursor,
            patterns=self._catalog.patterns(subscription.topics),
            limit=self.settings.replay_limit + 1,
        )
        if len(delta.rows) > self.settings.replay_limit:
            return [ResetItem()]
        events = [
            event
            for row in delta.rows
            for event in self._catalog.events_for(row)
            if event.topic in subscription.topics
        ]
        if not events:
            return []
        items: list[StreamItem] = [
            ChangeItem(event=event, cursor=last_event_id) for event in events[:-1]
        ]
        items.append(ChangeItem(event=events[-1], cursor=delta.snapshot.cursor()))
        return items

    def signal(self, organization_id: UUID, change_xid: int) -> None:
        if not self.hub.tracked(organization_id):
            return
        arrival = self._arrival[organization_id]
        if change_xid not in arrival:
            self._arrival_counter += 1
            arrival[change_xid] = self._arrival_counter
        self._dirty.add(organization_id)
        self._wake.set()

    def _on_connected(self) -> None:
        # Anything committed while disconnected is read now; nothing is skipped.
        self._dirty.update(self.hub.tracked_organizations())
        self._wake.set()

    async def _process(self, stop: asyncio.Event) -> None:
        retry_seconds = 0.5
        while not stop.is_set():
            await self._wake.wait()
            self._wake.clear()
            organizations, self._dirty = self._dirty, set()
            failed = False
            for organization_id in organizations:
                try:
                    await self.read_and_deliver(organization_id)
                except (SQLAlchemyError, OSError, TimeoutError) as exc:
                    _LOGGER.warning("change feed read failed: %s", type(exc).__name__)
                    self._dirty.add(organization_id)
                    failed = True
            if failed:
                with suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=retry_seconds)
                retry_seconds = min(retry_seconds * 2, 30.0)
                self._wake.set()
            else:
                retry_seconds = 0.5

    async def read_and_deliver(self, organization_id: UUID) -> None:
        previous = self.hub.baselines.get(organization_id)
        if previous is None:
            self._arrival.pop(organization_id, None)
            return
        delta = await self._reader.read_since(
            organization_id,
            previous,
            patterns=self._catalog.patterns(self._catalog.topics),
            limit=self.settings.batch_limit + 1,
        )
        if self.hub.baselines.get(organization_id) is not previous:
            # Re-tracked with a new baseline while reading: read again from it.
            if self.hub.tracked(organization_id):
                self._dirty.add(organization_id)
                self._wake.set()
            return
        arrival = self._arrival.get(organization_id, {})
        if len(delta.rows) > self.settings.batch_limit:
            self.hub.reset(organization_id)
        else:
            ordered = sorted(
                delta.rows,
                key=lambda row: (
                    arrival.get(row.change_xid, math.inf),
                    row.change_xid,
                    row.event_id,
                ),
            )
            events = [event for row in ordered for event in self._catalog.events_for(row)]
            if events:
                self.hub.deliver(organization_id, events, previous=previous, current=delta.snapshot)
        self.hub.baselines[organization_id] = delta.snapshot
        horizon = _snapshot_xmin(delta.snapshot)
        delivered = {row.change_xid for row in delta.rows}
        for xid in [xid for xid in arrival if xid in delivered or xid < horizon]:
            del arrival[xid]
