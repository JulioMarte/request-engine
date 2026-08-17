import asyncio
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID, uuid4

import pytest

from request_engine.platform.worker.runtime import (
    FencedWorkerRuntime,
    WorkerItemState,
    WorkerRuntimeConfig,
)
from request_engine.platform.worker.supervisor import WorkerSupervisor


@dataclass(frozen=True, slots=True)
class _Lease:
    id: UUID
    attempt_count: int = 1


class _Store:
    def __init__(self, lease: _Lease, *, renew_result: bool = True) -> None:
        self.lease = lease
        self.renew_result = renew_result
        self.claimed = False
        self.complete_calls = 0
        self.retry_calls: list[tuple[timedelta, str]] = []
        self.dead_calls = 0
        self.renew_calls = 0
        self.renewed = asyncio.Event()

    async def claim(self, *, limit: int, lease: timedelta) -> tuple[_Lease, ...]:
        assert limit == 1
        assert lease > timedelta(0)
        if self.claimed:
            return ()
        self.claimed = True
        return (self.lease,)

    async def complete(self, lease: _Lease) -> bool:
        assert lease == self.lease
        self.complete_calls += 1
        return True

    async def retry_after(
        self,
        lease: _Lease,
        *,
        delay: timedelta,
        error_class: str,
    ) -> str:
        assert lease == self.lease
        self.retry_calls.append((delay, error_class))
        return "pending"

    async def dead_letter(self, lease: _Lease, *, error_class: str) -> bool:
        assert lease == self.lease
        assert error_class
        self.dead_calls += 1
        return True

    async def renew(self, lease: _Lease, *, extension: timedelta) -> bool:
        assert lease == self.lease
        assert extension > timedelta(0)
        self.renew_calls += 1
        self.renewed.set()
        return self.renew_result


class _HangingProcessor:
    def __init__(self) -> None:
        self.cancelled = asyncio.Event()

    async def process(self, lease: _Lease) -> None:
        del lease
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise


class _SlowProcessor:
    def __init__(self, release: asyncio.Event) -> None:
        self.release = release

    async def process(self, lease: _Lease) -> None:
        del lease
        await self.release.wait()


def _config(*, processing_timeout: timedelta) -> WorkerRuntimeConfig:
    return WorkerRuntimeConfig(
        max_concurrency=1,
        claim_batch_size=1,
        lease_duration=timedelta(milliseconds=100),
        heartbeat_interval=timedelta(milliseconds=20),
        processing_timeout=processing_timeout,
        idle_sleep=timedelta(milliseconds=1),
        retry_base=timedelta(0),
        retry_cap=timedelta(0),
        retry_jitter_fraction=0.0,
    )


@pytest.mark.asyncio
async def test_processing_timeout_cancels_handler_and_becomes_retryable_work() -> None:
    lease = _Lease(uuid4())
    store = _Store(lease)
    processor = _HangingProcessor()
    runtime = FencedWorkerRuntime(
        store,
        processor,
        config=_config(processing_timeout=timedelta(milliseconds=70)),
    )

    outcome = (await runtime.run_once())[0]

    assert outcome.work_id == lease.id
    assert outcome.state is WorkerItemState.RETRY
    assert outcome.detail == "processing_timeout"
    assert processor.cancelled.is_set()
    assert store.complete_calls == 0
    assert store.dead_calls == 0
    assert store.retry_calls == [(timedelta(0), "processing_timeout")]
    assert store.renew_calls >= 1


@pytest.mark.asyncio
async def test_lost_heartbeat_prevents_finalization_even_when_handler_returns() -> None:
    lease = _Lease(uuid4())
    store = _Store(lease, renew_result=False)
    release = asyncio.Event()
    processor = _SlowProcessor(release)
    runtime = FencedWorkerRuntime(
        store,
        processor,
        config=_config(processing_timeout=timedelta(seconds=1)),
    )

    task = asyncio.create_task(runtime.run_once())
    await store.renewed.wait()
    release.set()
    outcome = (await task)[0]

    assert outcome.work_id == lease.id
    assert outcome.state is WorkerItemState.STALE
    assert outcome.detail == "lease_lost"
    assert store.complete_calls == 0
    assert store.retry_calls == []
    assert store.dead_calls == 0


class _FailingLoop:
    def __init__(self, sibling_started: asyncio.Event) -> None:
        self.sibling_started = sibling_started

    async def run_forever(self, stop_event: asyncio.Event) -> None:
        del stop_event
        await self.sibling_started.wait()
        raise RuntimeError("worker stream failed")


class _SiblingLoop:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def run_forever(self, stop_event: asyncio.Event) -> None:
        del stop_event
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise


@pytest.mark.asyncio
async def test_supervisor_stream_failure_cancels_siblings_and_propagates() -> None:
    sibling = _SiblingLoop()
    supervisor = WorkerSupervisor(
        {
            "scheduled_actions": _FailingLoop(sibling.started),
            "outbox_messages": sibling,
        }
    )

    with pytest.raises(ExceptionGroup) as exc_info:
        await supervisor.run(asyncio.Event())

    assert any(
        isinstance(error, RuntimeError) and str(error) == "worker stream failed"
        for error in exc_info.value.exceptions
    )
    assert sibling.cancelled.is_set()


class _CountingLoop:
    def __init__(self) -> None:
        self.calls = 0

    async def run_forever(self, stop_event: asyncio.Event) -> None:
        self.calls += 1
        assert stop_event.is_set()


@pytest.mark.asyncio
async def test_supervisor_shares_pre_set_graceful_stop_event_with_all_streams() -> None:
    stop_event = asyncio.Event()
    stop_event.set()
    scheduled = _CountingLoop()
    outbox = _CountingLoop()
    provider = _CountingLoop()
    supervisor = WorkerSupervisor(
        {
            "scheduled_actions": scheduled,
            "outbox_messages": outbox,
            "provider_events": provider,
        }
    )

    await supervisor.run(stop_event)

    assert scheduled.calls == 1
    assert outbox.calls == 1
    assert provider.calls == 1
