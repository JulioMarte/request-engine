import asyncio
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID, uuid4

import pytest

from request_engine.platform.worker.runtime import (
    FencedWorkerRuntime,
    LeaseLostWorkError,
    PermanentWorkError,
    RejectedWorkError,
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
        self.rejected: list[tuple[UUID, str]] = []
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

    async def reject(self, lease: FakeLease, *, error_class: str) -> bool:
        self.rejected.append((lease.id, error_class))
        return True

    async def renew(self, lease: FakeLease, *, extension: timedelta) -> bool:
        del extension
        self.renewed.append(lease.id)
        return self.renew_result


class RaisingRenewStore(FakeStore):
    async def renew(self, lease: FakeLease, *, extension: timedelta) -> bool:
        del extension
        self.renewed.append(lease.id)
        raise RuntimeError("database unavailable during heartbeat")


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


class RejectedProcessor:
    async def process(self, lease: FakeLease) -> None:
        del lease
        raise RejectedWorkError("unsupported_provider_payload")


class LeaseLostProcessor:
    async def process(self, lease: FakeLease) -> None:
        del lease
        raise LeaseLostWorkError("authoritative fence lost")


class SlowProcessor:
    async def process(self, lease: FakeLease) -> None:
        del lease
        await asyncio.sleep(0.03)


class HangingProcessor:
    async def process(self, lease: FakeLease) -> None:
        del lease
        await asyncio.sleep(60)


def _config(
    *,
    max_concurrency: int = 2,
    claim_batch_size: int = 10,
    processing_timeout: timedelta = timedelta(seconds=1),
    retry_jitter_fraction: float = 0.0,
) -> WorkerRuntimeConfig:
    return WorkerRuntimeConfig(
        max_concurrency=max_concurrency,
        claim_batch_size=claim_batch_size,
        lease_duration=timedelta(milliseconds=50),
        heartbeat_interval=timedelta(milliseconds=5),
        processing_timeout=processing_timeout,
        idle_sleep=timedelta(milliseconds=1),
        retry_base=timedelta(seconds=3),
        retry_cap=timedelta(seconds=30),
        retry_jitter_fraction=retry_jitter_fraction,
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


@pytest.mark.unit
def test_runtime_config_rejects_unbounded_or_spinning_process_settings() -> None:
    with pytest.raises(ValueError):
        WorkerRuntimeConfig(max_concurrency=501)
    with pytest.raises(ValueError):
        WorkerRuntimeConfig(idle_sleep=timedelta(0))
    with pytest.raises(ValueError):
        WorkerRuntimeConfig(idle_sleep=timedelta(seconds=61))


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
async def test_retry_jitter_is_stable_and_bounded_for_work_identity() -> None:
    lease = FakeLease(UUID("11111111-2222-3333-4444-555555555555"), 2)
    config = _config(retry_jitter_fraction=0.2)
    first_store = FakeStore((lease,))
    second_store = FakeStore((lease,))

    first = FencedWorkerRuntime(first_store, RetryProcessor(), config=config)
    second = FencedWorkerRuntime(second_store, RetryProcessor(), config=config)

    await first.run_once()
    await second.run_once()

    first_delay = first_store.retried[0][1]
    second_delay = second_store.retried[0][1]
    assert first_delay == second_delay
    assert timedelta(seconds=4.8) <= first_delay <= timedelta(seconds=7.2)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_processing_timeout_retries_instead_of_renewing_forever() -> None:
    lease = FakeLease(uuid4(), 1)
    store = FakeStore((lease,))
    runtime = FencedWorkerRuntime(
        store,
        HangingProcessor(),
        config=_config(
            max_concurrency=1,
            processing_timeout=timedelta(milliseconds=15),
        ),
    )

    outcome = (await runtime.run_once())[0]

    assert outcome.state is WorkerItemState.RETRY
    assert store.retried[0][0] == lease.id
    assert store.retried[0][2] == "processing_timeout"
    assert store.completed == []
    assert store.dead == []
    assert store.renewed


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
async def test_semantic_rejection_uses_explicit_rejecter_not_dead_letter() -> None:
    lease = FakeLease(uuid4(), 1)
    store = FakeStore((lease,))
    runtime = FencedWorkerRuntime(
        store,
        RejectedProcessor(),
        rejecter=store.reject,
        config=_config(),
    )

    outcome = (await runtime.run_once())[0]

    assert outcome.state is WorkerItemState.REJECTED
    assert outcome.detail == "unsupported_provider_payload"
    assert store.rejected == [(lease.id, "unsupported_provider_payload")]
    assert store.dead == []
    assert store.retried == []
    assert store.completed == []


@pytest.mark.asyncio
@pytest.mark.unit
async def test_semantic_rejection_without_rejecter_fails_loudly() -> None:
    lease = FakeLease(uuid4(), 1)
    store = FakeStore((lease,))
    runtime = FencedWorkerRuntime(store, RejectedProcessor(), config=_config())

    with pytest.raises(RuntimeError, match="rejection without a rejecter"):
        await runtime.run_once()

    assert store.dead == []
    assert store.retried == []
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


@pytest.mark.asyncio
@pytest.mark.unit
async def test_heartbeat_database_failure_is_treated_as_uncertain_ownership() -> None:
    lease = FakeLease(uuid4(), 1)
    store = RaisingRenewStore((lease,))
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


@pytest.mark.asyncio
@pytest.mark.unit
async def test_processor_signaled_lease_loss_never_mutates_work_state() -> None:
    lease = FakeLease(uuid4(), 1)
    store = FakeStore((lease,))
    runtime = FencedWorkerRuntime(store, LeaseLostProcessor(), config=_config())

    outcome = (await runtime.run_once())[0]

    assert outcome.state is WorkerItemState.STALE
    assert outcome.detail == "lease_lost"
    assert store.completed == []
    assert store.retried == []
    assert store.dead == []
