from datetime import datetime, timedelta

import pytest

from request_engine.entrypoints.worker.runtime import (
    OutboxBatchRunner,
    ScheduledActionBatchRunner,
)
from request_engine.platform.outbox.postgres import OutboxMessageLease
from request_engine.platform.scheduling.postgres import ScheduledActionLease


class EmptyScheduler:
    def __init__(self) -> None:
        self.claim_limits: list[int] = []

    async def claim(
        self,
        *,
        limit: int = 50,
        lease: timedelta = timedelta(seconds=60),
    ) -> tuple[ScheduledActionLease, ...]:
        del lease
        self.claim_limits.append(limit)
        return ()

    async def complete(self, lease: ScheduledActionLease) -> bool:
        del lease
        return True

    async def retry(
        self,
        lease: ScheduledActionLease,
        *,
        next_attempt_at: datetime,
        error_class: str,
    ) -> str:
        del lease, next_attempt_at, error_class
        return "pending"

    async def dead_letter(self, lease: ScheduledActionLease, *, error_class: str) -> bool:
        del lease, error_class
        return True


class EmptyOutbox:
    def __init__(self) -> None:
        self.claim_limits: list[int] = []

    async def claim(
        self,
        *,
        limit: int = 50,
        lease: timedelta = timedelta(seconds=60),
    ) -> tuple[OutboxMessageLease, ...]:
        del lease
        self.claim_limits.append(limit)
        return ()

    async def complete(self, lease: OutboxMessageLease) -> bool:
        del lease
        return True

    async def retry(
        self,
        lease: OutboxMessageLease,
        *,
        next_attempt_at: datetime,
        error_class: str,
    ) -> str:
        del lease, next_attempt_at, error_class
        return "pending"

    async def dead_letter(self, lease: OutboxMessageLease, *, error_class: str) -> bool:
        del lease, error_class
        return True


class NoopPublisher:
    async def publish(self, message: OutboxMessageLease) -> None:
        del message


@pytest.mark.asyncio
async def test_scheduled_runner_never_overclaims_beyond_concurrency() -> None:
    scheduler = EmptyScheduler()
    runner = ScheduledActionBatchRunner(scheduler, {}, max_concurrency=3)

    report = await runner.run_once(limit=50)

    assert report.claimed == 0
    assert scheduler.claim_limits == [3]


@pytest.mark.asyncio
async def test_outbox_runner_never_overclaims_beyond_concurrency() -> None:
    outbox = EmptyOutbox()
    runner = OutboxBatchRunner(outbox, NoopPublisher(), max_concurrency=4)

    report = await runner.run_once(limit=50)

    assert report.claimed == 0
    assert outbox.claim_limits == [4]


@pytest.mark.asyncio
async def test_batch_limit_validation_prevents_unbounded_claims() -> None:
    scheduler = EmptyScheduler()
    runner = ScheduledActionBatchRunner(scheduler, {}, max_concurrency=3)

    with pytest.raises(ValueError, match="limit must be between 1 and 500"):
        await runner.run_once(limit=501)

    assert scheduler.claim_limits == []
