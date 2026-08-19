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


class WorkerProcess:
    """Run every durable technical stream under one process boundary."""

    _STREAM_NAMES = ("scheduled_actions", "outbox_messages", "provider_events")

    def __init__(
        self,
        *,
        scheduled_actions: WorkerRuntime,
        outbox_messages: WorkerRuntime,
        provider_events: WorkerRuntime,
    ) -> None:
        self._scheduled_actions = scheduled_actions
        self._outbox_messages = outbox_messages
        self._provider_events = provider_events
        self._supervisor = WorkerSupervisor(
            {
                "scheduled_actions": scheduled_actions,
                "outbox_messages": outbox_messages,
                "provider_events": provider_events,
            }
        )

    @property
    def stream_names(self) -> tuple[str, ...]:
        return self._STREAM_NAMES

    async def run_once(self) -> WorkerCycleReport:
        scheduled_actions, outbox_messages, provider_events = await asyncio.gather(
            self._scheduled_actions.run_once(),
            self._outbox_messages.run_once(),
            self._provider_events.run_once(),
        )
        return WorkerCycleReport(
            scheduled_actions=scheduled_actions,
            outbox_messages=outbox_messages,
            provider_events=provider_events,
        )

    async def run(self, stop_event: asyncio.Event) -> None:
        """Run until graceful shutdown or propagate any failed stream."""

        await self._supervisor.run(stop_event)
