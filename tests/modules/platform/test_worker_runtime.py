import asyncio
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID, uuid4

import pytest

from request_engine.platform.worker.runtime import (
    FencedWorkerRuntime,
    PermanentWorkError,
    RetryableWorkError,
    WorkerItemState,
    WorkerRuntimeConfig,
)


@dataclass(frozen=True, slots=True)
class FakeLease:
    id: UUID
    attempt_count: int


class FakeStore:
    def __init__(self, leases: tuple[FakeLease, ...], *, renew_result: bool = True) -> None:
        self.leases = leases
        self.renew_result = renew_result
        self.last_claim_limit: int | None = None
        self.completed: list[UUID] = []
        self.retried: list[tuple[UUID, timedelta, str]] = []
        self.dead: list[tuple[UUID, str]] = []
        self.renewed: list[UUID] = []

    async def claim(self, *, limit: int, lease: timedelta) -> tuple[FakeLease, ...]:
        del lease
        self.last_claim_limit = limit
        claimed, self.leases = self.leases[:limit], self.leases[limit:]
        return claimed

    async def complete(self, lease: FakeLease) -> bool:
        self.completed.append(lease.id)
        return True

    async def retry_after(
        self,
        lease: FakeLease,
        *,
        delay: timedelta,
        error_class: str,
    ) -> str:
        self.retried.append((lease.id, delay, error_class))
        return "pending"

    async def dead_letter(self, lease: FakeLease, *, error_class: str) -> bool:
        self.dead.append((lease.id, error_class))
        return True

    async def renew(self, lease: FakeLease, *, extension: timedelta) -> bool:
        del extension
        self.renewed.append(lease.id)
        return self.renew_result


class SuccessProcessor:
    async def process(self, lease: FakeLease) -> None:
        del lease


class RetryProcessor:
    async def process(self, lease: FakeLease) -> None:
        del lease
        raise RetryableWorkError("temporary_dependency")


class PermanentProcessor:
    async def process(self, lease: FakeLease) -> None:
        del lease
        raise PermanentWorkError("invalid_work")


class SlowProcessor:
    async def process(self, lease: FakeLease) -> None:
        del lease
        await asyncio.sleep(0.03)


def _config(
    *,
    max_concurrency: int = 2,
    claim_batch_size: int = 10,
) -> WorkerRuntimeConfig:
    return WorkerRuntimeConfig(
        max_concurrency=max_concurrency,
        claim_batch_size=claim_batch_size,
        lease_duration=timedelta(milliseconds=50),
        heartbeat_interval=timedelta(milliseconds=5),
        idle_sleep=timedelta(0),
        retry_base=timedelta(seconds=3),
        retry_cap=timedelta(seconds=30),
    )


@pytest.mark.asyncio
@pytest.mark.unit
async def test_runtime_never_claims_more_than_concurrency_capacity() -> None:
    store = FakeStore(tuple(FakeLease(uuid4(), 1) for _ in range(5)))
    runtime = FencedWorkerRuntime(store, SuccessProcessor(), config=_config())

    outcomes = await runtime.run_once()

    assert store.last_claim_limit == 2
    assert len(outcomes) == 2
    assert all(outcome.state is WorkerItemState.COMPLETED for outcome in outcomes)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_retryable_failure_uses_deterministic_backoff() -> None:
    lease = FakeLease(uuid4(), 2)
    store = FakeStore((lease,))
    runtime = FencedWorkerRuntime(store, RetryProcessor(), config=_config())

    outcome = (await runtime.run_once())[0]

    assert outcome.state is WorkerItemState.RETRY
    assert store.retried == [(lease.id, timedelta(seconds=6), "temporary_dependency")]
    assert store.completed == []


@pytest.mark.asyncio
@pytest.mark.unit
async def test_permanent_failure_dead_letters_current_lease() -> None:
    lease = FakeLease(uuid4(), 1)
    store = FakeStore((lease,))
    runtime = FencedWorkerRuntime(store, PermanentProcessor(), config=_config())

    outcome = (await runtime.run_once())[0]

    assert outcome.state is WorkerItemState.DEAD
    assert store.dead == [(lease.id, "invalid_work")]
    assert store.completed == []


@pytest.mark.asyncio
@pytest.mark.unit
async def test_heartbeat_loss_fences_late_worker_from_finalization() -> None:
    lease = FakeLease(uuid4(), 1)
    store = FakeStore((lease,), renew_result=False)
    runtime = FencedWorkerRuntime(
        store,
        SlowProcessor(),
        config=_config(max_concurrency=1),
    )

    outcome = (await runtime.run_once())[0]

    assert outcome.state is WorkerItemState.STALE
    assert store.renewed == [lease.id]
    assert store.completed == []
    assert store.retried == []
    assert store.dead == []
