import asyncio
from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol

from request_engine.modules.operational_recovery.adapters.db.recovery_sweep_store import (
    RecoverySweepScope,
)
from request_engine.platform.worker.runtime import WorkerItemOutcome, WorkerItemState

_MIN_INTERVAL = timedelta(seconds=60)
_MAX_INTERVAL = timedelta(hours=1)


class RecoverySweepStore(Protocol):
    async def find_scopes(self, *, limit: int, offset: int) -> list[RecoverySweepScope]: ...

    async def repair_scope(self, scope: RecoverySweepScope) -> bool: ...


@dataclass(frozen=True, slots=True)
class RecoverySweepConfig:
    interval: timedelta = timedelta(seconds=300)
    batch_limit: int = 200

    def __post_init__(self) -> None:
        if not _MIN_INTERVAL <= self.interval <= _MAX_INTERVAL:
            raise ValueError("recovery sweep interval must be between 60s and 1h")
        if not 1 <= self.batch_limit <= 500:
            raise ValueError("recovery sweep batch_limit must be between 1 and 500")


class RecoverySweepRuntime:
    """Periodic bounded repair of lost F5 reassessment wake-ups.

    One tick examines at most ``batch_limit`` scopes with a rotating cursor and
    re-enqueues only wake-ups missing for the current authoritative revision.
    The sweep never evaluates F4 or resuscitates dead/cancelled actions; the
    existing fenced reassessment handler owns all evaluation semantics.
    """

    def __init__(
        self,
        store: RecoverySweepStore,
        config: RecoverySweepConfig | None = None,
    ) -> None:
        self._store = store
        self._config = config or RecoverySweepConfig()
        self._offset = 0

    async def run_once(self) -> tuple[WorkerItemOutcome, ...]:
        scopes = await self._store.find_scopes(
            limit=self._config.batch_limit,
            offset=self._offset,
        )
        if len(scopes) < self._config.batch_limit:
            self._offset = 0
        else:
            self._offset += self._config.batch_limit
        outcomes: list[WorkerItemOutcome] = []
        for scope in scopes:
            if await self._store.repair_scope(scope):
                outcomes.append(
                    WorkerItemOutcome(
                        work_id=scope.service_queue_id,
                        state=WorkerItemState.COMPLETED,
                        detail="recovery_sweep_repaired",
                    )
                )
        return tuple(outcomes)

    async def run_forever(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            await self.run_once()
            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=self._config.interval.total_seconds(),
                )
            except TimeoutError:
                continue
