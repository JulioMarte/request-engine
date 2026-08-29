import asyncio
from dataclasses import dataclass
from typing import Protocol

from request_engine.platform.worker.runtime import WorkerItemOutcome
from request_engine.platform.worker.supervisor import WorkerSupervisor


class WorkerRuntime(Protocol):
    async def run_once(self) -> tuple[WorkerItemOutcome, ...]: ...

    async def run_forever(self, stop_event: asyncio.Event) -> None: ...


@dataclass(frozen=True, slots=True)
class WorkerCycleReport:
    scheduled_actions: tuple[WorkerItemOutcome, ...]
    outbox_messages: tuple[WorkerItemOutcome, ...]
    provider_events: tuple[WorkerItemOutcome, ...]
    recovery_sweep: tuple[WorkerItemOutcome, ...] = ()


class WorkerProcess:
    """Run every durable technical stream under one process boundary."""

    _BASE_STREAM_NAMES = ("scheduled_actions", "outbox_messages", "provider_events")

    def __init__(
        self,
        *,
        scheduled_actions: WorkerRuntime,
        outbox_messages: WorkerRuntime,
        provider_events: WorkerRuntime,
        recovery_sweep: WorkerRuntime | None = None,
    ) -> None:
        self._runtimes: dict[str, WorkerRuntime] = {
            "scheduled_actions": scheduled_actions,
            "outbox_messages": outbox_messages,
            "provider_events": provider_events,
        }
        if recovery_sweep is not None:
            self._runtimes["recovery_sweep"] = recovery_sweep
        self._supervisor = WorkerSupervisor(self._runtimes)

    @property
    def stream_names(self) -> tuple[str, ...]:
        return tuple(self._runtimes)

    async def run_once(self) -> WorkerCycleReport:
        results = await asyncio.gather(*(runtime.run_once() for runtime in self._runtimes.values()))
        outcomes = dict(zip(self._runtimes, results, strict=True))
        return WorkerCycleReport(
            scheduled_actions=outcomes["scheduled_actions"],
            outbox_messages=outcomes["outbox_messages"],
            provider_events=outcomes["provider_events"],
            recovery_sweep=outcomes.get("recovery_sweep", ()),
        )

    async def run(self, stop_event: asyncio.Event) -> None:
        """Run until graceful shutdown or propagate any failed stream."""

        await self._supervisor.run(stop_event)
