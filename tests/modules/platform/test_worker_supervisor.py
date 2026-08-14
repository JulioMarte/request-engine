import asyncio
from dataclasses import dataclass, field

import pytest

from request_engine.platform.worker.supervisor import WorkerSupervisor


@dataclass
class BlockingWorker:
    started: asyncio.Event = field(default_factory=asyncio.Event)
    cancelled: asyncio.Event = field(default_factory=asyncio.Event)

    async def run_forever(self, stop_event: asyncio.Event) -> None:
        self.started.set()
        try:
            await stop_event.wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise


@dataclass
class FailingWorker:
    started: asyncio.Event = field(default_factory=asyncio.Event)

    async def run_forever(self, stop_event: asyncio.Event) -> None:
        del stop_event
        self.started.set()
        raise RuntimeError("worker loop failed")


@pytest.mark.asyncio
@pytest.mark.unit
async def test_supervisor_shares_graceful_stop_with_all_workers() -> None:
    first = BlockingWorker()
    second = BlockingWorker()
    stop_event = asyncio.Event()
    supervisor = WorkerSupervisor({"scheduled": first, "outbox": second})

    task = asyncio.create_task(supervisor.run(stop_event))
    await first.started.wait()
    await second.started.wait()
    stop_event.set()
    await task

    assert first.cancelled.is_set() is False
    assert second.cancelled.is_set() is False


@pytest.mark.asyncio
@pytest.mark.unit
async def test_supervisor_cancels_siblings_when_one_loop_fails() -> None:
    sibling = BlockingWorker()
    failing = FailingWorker()
    stop_event = asyncio.Event()
    supervisor = WorkerSupervisor({"sibling": sibling, "failing": failing})

    try:
        await supervisor.run(stop_event)
    except* RuntimeError as errors:
        assert len(errors.exceptions) == 1
        assert str(errors.exceptions[0]) == "worker loop failed"
    else:
        pytest.fail("supervisor must propagate worker failure")

    assert sibling.cancelled.is_set() is True


@pytest.mark.unit
def test_supervisor_rejects_empty_runtime_set() -> None:
    with pytest.raises(ValueError, match="at least one worker loop"):
        WorkerSupervisor({})
