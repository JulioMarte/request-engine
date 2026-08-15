import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from request_engine.platform.outbox.postgres import OutboxMessageLease
from request_engine.platform.scheduling.postgres import ScheduledActionLease
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
    """Claim only immediately runnable leases and route them to owning modules."""

    def __init__(
        self,
        scheduler: ScheduledActionLeaseStore,
        processors: Mapping[str, ScheduledActionProcessor],
        *,
        max_concurrency: int = 10,
    ) -> None:
        if max_concurrency <= 0 or max_concurrency > 100:
            raise ValueError("max_concurrency must be between 1 and 100")
        self._scheduler = scheduler
        self._processors = processors
        self._max_concurrency = max_concurrency

    async def run_once(self, *, limit: int = 50) -> WorkerCycleReport:
        if limit <= 0 or limit > 500:
            raise ValueError("limit must be between 1 and 500")

        claim_limit = min(limit, self._max_concurrency)
        leases = await self._scheduler.claim(limit=claim_limit)
        dispositions = await asyncio.gather(*(self._process_one(lease) for lease in leases))
        counts = {state: dispositions.count(state) for state in ScheduledActionDisposition}

        return WorkerCycleReport(
            claimed=len(leases),
            completed=counts[ScheduledActionDisposition.COMPLETED],
            deferred=counts[ScheduledActionDisposition.DEFERRED],
            dead=counts[ScheduledActionDisposition.DEAD],
            stale=counts[ScheduledActionDisposition.STALE],
        )

    async def _process_one(self, lease: ScheduledActionLease) -> ScheduledActionDisposition:
        processor = self._processors.get(lease.owner_module)
        if processor is None:
            finalized = await self._scheduler.dead_letter(
                lease,
                error_class=f"unsupported_owner_module:{lease.owner_module}",
            )
            return (
                ScheduledActionDisposition.DEAD
                if finalized
                else ScheduledActionDisposition.STALE
            )

        try:
            result = await processor.process(lease)
        except Exception as exc:
            retry_state = await self._scheduler.retry(
                lease,
                next_attempt_at=datetime.now(UTC) + retry_delay(lease.attempt_count),
                error_class=type(exc).__name__,
            )
            return {
                "pending": ScheduledActionDisposition.DEFERRED,
                "dead": ScheduledActionDisposition.DEAD,
                "stale": ScheduledActionDisposition.STALE,
            }.get(retry_state, ScheduledActionDisposition.STALE)

        return result.disposition


class OutboxBatchRunner:
    """Publish only immediately runnable leases with bounded I/O concurrency."""

    def __init__(
        self,
        outbox: OutboxLeaseStore,
        publisher: OutboxPublisher,
        *,
        max_concurrency: int = 10,
    ) -> None:
        if max_concurrency <= 0 or max_concurrency > 100:
            raise ValueError("max_concurrency must be between 1 and 100")
        self._outbox = outbox
        self._publisher = publisher
        self._max_concurrency = max_concurrency

    async def run_once(self, *, limit: int = 50) -> WorkerCycleReport:
        if limit <= 0 or limit > 500:
            raise ValueError("limit must be between 1 and 500")

        claim_limit = min(limit, self._max_concurrency)
        leases = await self._outbox.claim(limit=claim_limit)
        dispositions = await asyncio.gather(*(self._process_one(lease) for lease in leases))
        counts = {state: dispositions.count(state) for state in ScheduledActionDisposition}

        return WorkerCycleReport(
            claimed=len(leases),
            completed=counts[ScheduledActionDisposition.COMPLETED],
            deferred=counts[ScheduledActionDisposition.DEFERRED],
            dead=counts[ScheduledActionDisposition.DEAD],
            stale=counts[ScheduledActionDisposition.STALE],
        )

    async def _process_one(self, lease: OutboxMessageLease) -> ScheduledActionDisposition:
        try:
            await self._publisher.publish(lease)
        except Exception as exc:
            retry_state = await self._outbox.retry(
                lease,
                next_attempt_at=datetime.now(UTC) + retry_delay(lease.attempt_count),
                error_class=type(exc).__name__,
            )
            return {
                "pending": ScheduledActionDisposition.DEFERRED,
                "dead": ScheduledActionDisposition.DEAD,
                "stale": ScheduledActionDisposition.STALE,
            }.get(retry_state, ScheduledActionDisposition.STALE)

        finalized = await self._outbox.complete(lease)
        return (
            ScheduledActionDisposition.COMPLETED
            if finalized
            else ScheduledActionDisposition.STALE
        )
