import asyncio
from collections.abc import Mapping
from typing import Protocol


class WorkerLoop(Protocol):
    async def run_forever(self, stop_event: asyncio.Event) -> None: ...


class WorkerSupervisor:
    """Run independent worker loops under one structured-concurrency boundary.

    The same stop event is shared by every loop for graceful shutdown. If any
    loop raises unexpectedly, ``TaskGroup`` cancels its siblings and propagates
    the failure instead of leaving a partially alive worker process.
    """

    def __init__(self, workers: Mapping[str, WorkerLoop]) -> None:
        if not workers:
            raise ValueError("at least one worker loop is required")
        if any(not name.strip() for name in workers):
            raise ValueError("worker loop names must be non-empty")
        self._workers = tuple(workers.items())

    async def run(self, stop_event: asyncio.Event) -> None:
        async with asyncio.TaskGroup() as task_group:
            for name, worker in self._workers:
                task_group.create_task(
                    worker.run_forever(stop_event),
                    name=f"request-engine:{name}",
                )
