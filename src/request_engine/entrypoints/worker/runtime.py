from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from request_engine.platform.outbox.postgres import OutboxMessageLease
from request_engine.platform.scheduling.worker import (
    ScheduledActionDisposition,
    ScheduledActionLeaseStore,
    ScheduledActionProcessor,
    retry_delay,
)


class OutboxPublisher(Protocol):
    async def publish(self, message: OutboxMessageLease) -> None: ...


class OutboxLeaseStore(Protocol):
    async def claim(
        self,
        *,
        limit: int = 50,
        lease: timedelta = timedelta(seconds=60),
    ) -> tuple[OutboxMessageLease, ...]: ...

    async def complete(self, lease: OutboxMessageLease) -> bool: ...

    async def retry(
        self,
        lease: OutboxMessageLease,
        *,
        next_attempt_at: datetime,
        error_class: str,
    ) -> str: ...

    async def dead_letter(self, lease: OutboxMessageLease, *, error_class: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class WorkerCycleReport:
    claimed: int = 0
    completed: int = 0
    deferred: int = 0
    dead: int = 0
    stale: int = 0


class ScheduledActionBatchRunner:
    """Claim and route one bounded batch without owning business action semantics."""

    def __init__(
        self,
        scheduler: ScheduledActionLeaseStore,
        processors: Mapping[str, ScheduledActionProcessor],
    ) -> None:
        self._scheduler = scheduler
        self._processors = processors

    async def run_once(self, *, limit: int = 50) -> WorkerCycleReport:
        leases = await self._scheduler.claim(limit=limit)
        counts = {state: 0 for state in ScheduledActionDisposition}

        for lease in leases:
            processor = self._processors.get(lease.owner_module)
            if processor is None:
                finalized = await self._scheduler.dead_letter(
                    lease,
                    error_class=f"unsupported_owner_module:{lease.owner_module}",
                )
                counts[
                    ScheduledActionDisposition.DEAD
                    if finalized
                    else ScheduledActionDisposition.STALE
                ] += 1
                continue

            try:
                result = await processor.process(lease)
            except Exception as exc:
                retry_state = await self._scheduler.retry(
                    lease,
                    next_attempt_at=datetime.now(UTC) + retry_delay(lease.attempt_count),
                    error_class=type(exc).__name__,
                )
                disposition = {
                    "pending": ScheduledActionDisposition.DEFERRED,
                    "dead": ScheduledActionDisposition.DEAD,
                    "stale": ScheduledActionDisposition.STALE,
                }.get(retry_state, ScheduledActionDisposition.STALE)
                counts[disposition] += 1
            else:
                counts[result.disposition] += 1

        return WorkerCycleReport(
            claimed=len(leases),
            completed=counts[ScheduledActionDisposition.COMPLETED],
            deferred=counts[ScheduledActionDisposition.DEFERRED],
            dead=counts[ScheduledActionDisposition.DEAD],
            stale=counts[ScheduledActionDisposition.STALE],
        )


class OutboxBatchRunner:
    """Publish one bounded outbox batch with provider I/O outside claim transactions."""

    def __init__(self, outbox: OutboxLeaseStore, publisher: OutboxPublisher) -> None:
        self._outbox = outbox
        self._publisher = publisher

    async def run_once(self, *, limit: int = 50) -> WorkerCycleReport:
        leases = await self._outbox.claim(limit=limit)
        completed = deferred = dead = stale = 0

        for lease in leases:
            try:
                await self._publisher.publish(lease)
            except Exception as exc:
                retry_state = await self._outbox.retry(
                    lease,
                    next_attempt_at=datetime.now(UTC) + retry_delay(lease.attempt_count),
                    error_class=type(exc).__name__,
                )
                if retry_state == "pending":
                    deferred += 1
                elif retry_state == "dead":
                    dead += 1
                else:
                    stale += 1
                continue

            finalized = await self._outbox.complete(lease)
            if finalized:
                completed += 1
            else:
                stale += 1

        return WorkerCycleReport(
            claimed=len(leases),
            completed=completed,
            deferred=deferred,
            dead=dead,
            stale=stale,
        )
