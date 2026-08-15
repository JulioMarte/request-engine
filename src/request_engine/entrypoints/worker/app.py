import asyncio
from collections.abc import Mapping
from dataclasses import dataclass

from request_engine.entrypoints.worker.runtime import (
    OutboxBatchRunner,
    OutboxPublisher,
    ScheduledActionBatchRunner,
    WorkerCycleReport,
)
from request_engine.modules.communications.contracts.delivery import CommunicationDeliveryProvider
from request_engine.modules.communications.worker import build_scheduled_action_worker
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.outbox.postgres import PostgresOutboxWorker
from request_engine.platform.scheduling.postgres import PostgresScheduledActionWorker


@dataclass(frozen=True, slots=True)
class RequestEngineWorkerReport:
    scheduled_actions: WorkerCycleReport
    outbox: WorkerCycleReport


class RequestEngineWorker:
    """Production process runtime for durable ScheduledAction and outbox work."""

    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        communication_providers: Mapping[str, CommunicationDeliveryProvider],
        outbox_publisher: OutboxPublisher,
        max_concurrency: int = 10,
    ) -> None:
        scheduler = PostgresScheduledActionWorker(session_factory)
        communications = build_scheduled_action_worker(
            session_factory,
            scheduler,
            communication_providers,
        )
        self._scheduled_actions = ScheduledActionBatchRunner(
            scheduler,
            {"communications": communications},
            max_concurrency=max_concurrency,
        )
        self._outbox = OutboxBatchRunner(
            PostgresOutboxWorker(session_factory),
            outbox_publisher,
            max_concurrency=max_concurrency,
        )

    async def run_once(self, *, batch_size: int = 50) -> RequestEngineWorkerReport:
        scheduled_report, outbox_report = await asyncio.gather(
            self._scheduled_actions.run_once(limit=batch_size),
            self._outbox.run_once(limit=batch_size),
        )
        return RequestEngineWorkerReport(
            scheduled_actions=scheduled_report,
            outbox=outbox_report,
        )

    async def run_forever(
        self,
        *,
        batch_size: int = 50,
        poll_interval_seconds: float = 1.0,
        stop_event: asyncio.Event | None = None,
    ) -> None:
        if batch_size <= 0 or batch_size > 500:
            raise ValueError("batch_size must be between 1 and 500")
        if poll_interval_seconds <= 0 or poll_interval_seconds > 60:
            raise ValueError("poll_interval_seconds must be > 0 and <= 60")

        stop = stop_event or asyncio.Event()
        while not stop.is_set():
            report = await self.run_once(batch_size=batch_size)
            if report.scheduled_actions.claimed == 0 and report.outbox.claimed == 0:
                await asyncio.sleep(poll_interval_seconds)
