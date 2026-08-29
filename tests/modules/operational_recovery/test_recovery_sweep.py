from datetime import timedelta
from uuid import UUID

import pytest

from request_engine.modules.operational_recovery.adapters.db.recovery_sweep_store import (
    RecoverySweepScope,
)
from request_engine.modules.operational_recovery.adapters.worker.recovery_sweep import (
    RecoverySweepConfig,
    RecoverySweepRuntime,
)
from request_engine.platform.worker.runtime import WorkerItemState

pytestmark = [pytest.mark.unit, pytest.mark.invariant, pytest.mark.contract]


class FakeSweepStore:
    def __init__(
        self,
        scopes: list[RecoverySweepScope],
        repair_queues: set[UUID],
    ) -> None:
        self.scopes = scopes
        self.repair_queues = repair_queues
        self.calls: list[tuple[int, int]] = []
        self.repairs: list[RecoverySweepScope] = []

    async def find_scopes(self, *, limit: int, offset: int) -> list[RecoverySweepScope]:
        self.calls.append((limit, offset))
        return self.scopes[offset : offset + limit]

    async def repair_scope(self, scope: RecoverySweepScope) -> bool:
        self.repairs.append(scope)
        return scope.service_queue_id in self.repair_queues


def test_sweep_config_bounds_are_enforced() -> None:
    with pytest.raises(ValueError):
        RecoverySweepConfig(interval=timedelta(seconds=59))
    with pytest.raises(ValueError):
        RecoverySweepConfig(interval=timedelta(hours=1, seconds=1))
    with pytest.raises(ValueError):
        RecoverySweepConfig(batch_limit=0)
    with pytest.raises(ValueError):
        RecoverySweepConfig(batch_limit=501)
    assert RecoverySweepConfig(interval=timedelta(seconds=60), batch_limit=1) is not None


@pytest.mark.asyncio
async def test_sweep_repairs_missing_wakeups_and_reports_outcomes() -> None:
    queues = [UUID(int=index) for index in range(1, 5)]
    scopes = [RecoverySweepScope(UUID(int=1), queue) for queue in queues]
    repaired = {UUID(int=1), UUID(int=3)}
    store = FakeSweepStore(scopes, repair_queues=repaired)
    runtime = RecoverySweepRuntime(
        store,
        RecoverySweepConfig(interval=timedelta(seconds=60), batch_limit=4),
    )

    outcomes = await runtime.run_once()

    assert store.calls == [(4, 0)]
    assert [outcome.state for outcome in outcomes] == [
        WorkerItemState.COMPLETED,
        WorkerItemState.COMPLETED,
    ]
    assert {outcome.work_id for outcome in outcomes} == repaired
    assert len(store.repairs) == 4


@pytest.mark.asyncio
async def test_sweep_cursor_rotates_across_ticks_and_wraps_at_end() -> None:
    queues = [UUID(int=index) for index in range(1, 7)]
    scopes = [RecoverySweepScope(UUID(int=1), queue) for queue in queues]
    store = FakeSweepStore(scopes, repair_queues=set())
    config = RecoverySweepConfig(interval=timedelta(seconds=60), batch_limit=4)
    runtime = RecoverySweepRuntime(store, config)

    await runtime.run_once()
    assert store.calls[-1] == (4, 0)
    await runtime.run_once()
    assert store.calls[-1] == (4, 4)
    await runtime.run_once()
    assert store.calls[-1] == (4, 0)


@pytest.mark.asyncio
async def test_sweep_with_no_scopes_is_clean_noop() -> None:
    store = FakeSweepStore([], repair_queues=set())
    runtime = RecoverySweepRuntime(store)

    assert await runtime.run_once() == ()
    assert store.repairs == []
    assert store.calls == [(200, 0)]
