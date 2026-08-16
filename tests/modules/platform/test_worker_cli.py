import asyncio
import signal
import sys
from types import ModuleType

import pytest

from request_engine.entrypoints.worker.cli import (
    _shutdown_signals,  # pyright: ignore[reportPrivateUsage]
    load_worker_process,
    run_worker,
)


class FakeProcess:
    def __init__(self) -> None:
        self.stop_event: asyncio.Event | None = None

    async def run(self, stop_event: asyncio.Event) -> None:
        self.stop_event = stop_event
        stop_event.set()


@pytest.mark.unit
def test_load_worker_process_uses_explicit_trusted_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    module = ModuleType("test_worker_deployment")
    process = FakeProcess()
    module.create_worker = lambda: process  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, module.__name__, module)

    assert load_worker_process("test_worker_deployment:create_worker") is process


@pytest.mark.unit
@pytest.mark.parametrize("factory_path", ["", "missing_separator", ":factory", "module:"])
def test_load_worker_process_rejects_invalid_factory_path(factory_path: str) -> None:
    with pytest.raises(ValueError, match="module:factory"):
        load_worker_process(factory_path)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_run_worker_uses_supplied_shutdown_event(monkeypatch: pytest.MonkeyPatch) -> None:
    module = ModuleType("test_worker_runtime_deployment")
    process = FakeProcess()
    module.create_worker = lambda: process  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, module.__name__, module)
    stop_event = asyncio.Event()

    await run_worker(
        "test_worker_runtime_deployment:create_worker",
        stop_event=stop_event,
    )

    assert process.stop_event is stop_event
    assert stop_event.is_set()


@pytest.mark.unit
def test_shutdown_signal_handlers_set_event_and_are_removed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    callbacks: dict[signal.Signals, object] = {}
    removed: list[signal.Signals] = []

    class FakeLoop:
        def add_signal_handler(
            self,
            shutdown_signal: signal.Signals,
            callback: object,
        ) -> None:
            callbacks[shutdown_signal] = callback

        def remove_signal_handler(self, shutdown_signal: signal.Signals) -> bool:
            removed.append(shutdown_signal)
            return True

    monkeypatch.setattr(asyncio, "get_running_loop", FakeLoop)
    stop_event = asyncio.Event()

    with _shutdown_signals(stop_event):
        callback = callbacks[signal.SIGTERM]
        assert callable(callback)
        callback()
        assert stop_event.is_set()

    assert removed == [signal.SIGINT, signal.SIGTERM]
