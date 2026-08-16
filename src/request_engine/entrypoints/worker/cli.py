import argparse
import asyncio
import importlib
import os
import signal
from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import Protocol, cast, runtime_checkable


@runtime_checkable
class RunnableWorkerProcess(Protocol):
    async def run(self, stop_event: asyncio.Event) -> None: ...


def load_worker_process(factory_path: str) -> RunnableWorkerProcess:
    """Load one trusted deployment factory configured as ``module:factory``."""

    module_name, separator, attribute_name = factory_path.partition(":")
    if not separator or not module_name or not attribute_name:
        raise ValueError("worker factory must use the form module:factory")

    module = importlib.import_module(module_name)
    factory = getattr(module, attribute_name, None)
    if not callable(factory):
        raise TypeError(f"worker factory {factory_path!r} is not callable")

    process = cast(Callable[[], object], factory)()
    if not isinstance(process, RunnableWorkerProcess):
        raise TypeError(f"worker factory {factory_path!r} did not return a runnable process")
    return process


@contextmanager
def _shutdown_signals(stop_event: asyncio.Event) -> Generator[None]:
    loop = asyncio.get_running_loop()
    installed: list[signal.Signals] = []
    for shutdown_signal in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(shutdown_signal, stop_event.set)
        except NotImplementedError:
            continue
        installed.append(shutdown_signal)
    try:
        yield
    finally:
        for shutdown_signal in installed:
            loop.remove_signal_handler(shutdown_signal)


async def run_worker(
    factory_path: str,
    *,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Load and run one process until SIGINT, SIGTERM, or an explicit stop event."""

    process = load_worker_process(factory_path)
    if stop_event is not None:
        await process.run(stop_event)
        return

    shutdown = asyncio.Event()
    with _shutdown_signals(shutdown):
        await process.run(shutdown)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Request Engine durable workers")
    parser.add_argument(
        "--factory",
        default=os.environ.get("REQUEST_ENGINE_WORKER_FACTORY"),
        help=(
            "trusted module:factory returning a configured WorkerProcess "
            "(or set REQUEST_ENGINE_WORKER_FACTORY)"
        ),
    )
    args = parser.parse_args()
    if not args.factory:
        parser.error(
            "--factory or REQUEST_ENGINE_WORKER_FACTORY is required; "
            "no transport adapters are inferred"
        )
    asyncio.run(run_worker(cast(str, args.factory)))
