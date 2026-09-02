import asyncio
from uuid import uuid4

import pytest

from f7e_selection_fixture import PgConnection, create_f7e_selection_fixture
from f7e_selection_race_barrier import AsyncTwoPartyBarrier, gated_lock
from request_engine.modules.queue.adapters.db import service_queue_commands as queue_module
from request_engine.modules.queue.adapters.db import skip_queue_head as skip_module
from request_engine.modules.queue.adapters.db.same_day_selection_commands import (
    PostgresSameDaySelectionCommands,
)
from request_engine.modules.queue.adapters.db.service_queue_commands import (
    PostgresServiceQueueCommands,
)
from request_engine.modules.queue.application.commands.call_next import CallNextCommand
from request_engine.modules.queue.application.commands.skip_queue_head import SkipQueueHeadCommand
from request_engine.modules.queue.contracts.same_day_selection import SkipReason, SkipResult
from request_engine.modules.queue.contracts.service_queue import QueueEntry
from request_engine.platform.db.session import SessionFactory

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.mark.asyncio
async def test_skip_vs_call_next_records_the_fifo_head_seen_under_queue_lock(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = create_f7e_selection_fixture(admin_conn)
    first, second, third = world.entry_ids
    barrier = AsyncTwoPartyBarrier()
    monkeypatch.setattr(
        queue_module,
        "_lock_active_queue",
        gated_lock(barrier, queue_module._lock_active_queue),
    )
    monkeypatch.setattr(
        skip_module,
        "lock_active_queue",
        gated_lock(barrier, skip_module.lock_active_queue),
    )
    queue = PostgresServiceQueueCommands(command_session_factory)
    f7e = PostgresSameDaySelectionCommands(command_session_factory)

    results = await asyncio.gather(
        queue.call_next(
            CallNextCommand(
                organization_id=world.organization_id,
                principal_id=world.principal_id,
                queue_id=world.queue_id,
                idempotency_key=f"call-skip-{uuid4().hex}",
            )
        ),
        f7e.skip_queue_head(
            SkipQueueHeadCommand(
                organization_id=world.organization_id,
                principal_id=world.principal_id,
                queue_id=world.queue_id,
                reason=SkipReason.NO_RESPONSE,
                idempotency_key=f"skip-race-{uuid4().hex}",
            )
        ),
    )

    ordinary = results[0]
    skipped = results[1]
    assert isinstance(ordinary, QueueEntry)
    assert isinstance(skipped, SkipResult)
    if ordinary.id == first:
        assert skipped.skipped_entry_id == second
        assert skipped.called_entry is not None and skipped.called_entry.id == third
    else:
        assert skipped.skipped_entry_id == first
        assert skipped.called_entry is not None and skipped.called_entry.id == second
        assert ordinary.id == first

    fact = admin_conn.execute(
        "SELECT queue_entry_id,called_queue_entry_id FROM request_engine.queue_selection_facts "
        "WHERE organization_id=%s AND selection_kind='skip'",
        (world.organization_id,),
    ).fetchone()
    assert fact == (skipped.skipped_entry_id, skipped.called_entry.id)
