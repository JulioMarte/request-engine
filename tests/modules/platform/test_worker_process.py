import asyncio
from dataclasses import dataclass, field
from uuid import uuid4

import pytest

from request_engine.entrypoints.worker.app import WorkerCycleReport, WorkerProcess
from request_engine.platform.worker.runtime import WorkerItemOutcome, WorkerItemState


@dataclass
class FakeRuntime:
    outcomes: tuple[WorkerItemOutcome, ...]
    started: asyncio.Event = field(default_factory=asyncio.Event)
    stopped: asyncio.Event = field(default_factory=asyncio.Event)

    async def run_once(self) -> tuple[WorkerItemOutcome, ...]:
        return self.outcomes

    async def run_forever(self, stop_event: asyncio.Event) -> None:
        self.started.set()
        await stop_event.wait()
        self.stopped.set()


def _outcome(state: WorkerItemState) -> WorkerItemOutcome:
    return WorkerItemOutcome(uuid4(), state, state.value)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_run_once_reports_every_durable_stream() -> None:
    scheduled = FakeRuntime((_outcome(WorkerItemState.COMPLETED),))
    outbox = FakeRuntime((_outcome(WorkerItemState.RETRY),))
    provider_events = FakeRuntime((_outcome(WorkerItemState.DEAD),))
    process = WorkerProcess(
        scheduled_actions=scheduled,
        outbox_messages=outbox,
        provider_events=provider_events,
    )

    report = await process.run_once()

    assert isinstance(report, WorkerCycleReport)
    assert report.scheduled_actions == scheduled.outcomes
    assert report.outbox_messages == outbox.outcomes
    assert report.provider_events == provider_events.outcomes
    assert process.stream_names == (
        "scheduled_actions",
        "outbox_messages",
        "provider_events",
    )


@pytest.mark.asyncio
@pytest.mark.unit
async def test_run_shares_graceful_shutdown_across_every_stream() -> None:
    scheduled = FakeRuntime(())
    outbox = FakeRuntime(())
    provider_events = FakeRuntime(())
    process = WorkerProcess(
        scheduled_actions=scheduled,
        outbox_messages=outbox,
        provider_events=provider_events,
    )
    stop_event = asyncio.Event()

    task = asyncio.create_task(process.run(stop_event))
    await asyncio.gather(
        scheduled.started.wait(),
        outbox.started.wait(),
        provider_events.started.wait(),
    )
    stop_event.set()
    await task

    assert scheduled.stopped.is_set()
    assert outbox.stopped.is_set()
    assert provider_events.stopped.is_set()
