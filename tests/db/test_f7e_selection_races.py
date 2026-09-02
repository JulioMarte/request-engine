import asyncio
from typing import cast
from uuid import UUID, uuid4

import pytest

from f7e_selection_fixture import PgConnection, create_f7e_selection_fixture
from f7e_selection_race_barrier import AsyncTwoPartyBarrier, gated_lock
from request_engine.modules.queue.adapters.db import recall_hold as recall_hold_module
from request_engine.modules.queue.adapters.db import service_queue_commands as queue_module
from request_engine.modules.queue.adapters.db.same_day_selection_commands import (
    PostgresSameDaySelectionCommands,
)
from request_engine.modules.queue.adapters.db.service_queue_commands import (
    PostgresServiceQueueCommands,
)
from request_engine.modules.queue.application.commands.call_next import CallNextCommand
from request_engine.modules.queue.application.commands.recall_hold import RecallHoldCommand
from request_engine.modules.queue.application.same_day_selection_errors import QueueEntryNotSelectable
from request_engine.modules.queue.contracts.same_day_selection import (
    RecallHold,
    RecallHoldKind,
    RecallHoldReason,
)
from request_engine.modules.queue.contracts.service_queue import QueueEntry
from request_engine.platform.db.session import SessionFactory

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.mark.asyncio
async def test_call_next_vs_recall_hold_serializes_without_called_held_state(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = create_f7e_selection_fixture(admin_conn)
    first, second, _third = world.entry_ids
    barrier = AsyncTwoPartyBarrier()
    original_queue_lock = queue_module._lock_active_queue
    original_hold_lock = recall_hold_module.lock_active_queue
    monkeypatch.setattr(
        queue_module,
        "_lock_active_queue",
        gated_lock(barrier, original_queue_lock),
    )
    monkeypatch.setattr(
        recall_hold_module,
        "lock_active_queue",
        gated_lock(barrier, original_hold_lock),
    )

    queue = PostgresServiceQueueCommands(command_session_factory)
    f7e = PostgresSameDaySelectionCommands(command_session_factory)
    results = await asyncio.gather(
        queue.call_next(
            CallNextCommand(
                organization_id=world.organization_id,
                principal_id=world.principal_id,
                queue_id=world.queue_id,
                idempotency_key=f"race-call-{uuid4().hex}",
            )
        ),
        f7e.recall_hold(
            RecallHoldCommand(
                organization_id=world.organization_id,
                principal_id=world.principal_id,
                queue_id=world.queue_id,
                queue_entry_id=first,
                expected_revision=1,
                kind=RecallHoldKind.UNTIL_CUSTOMER_INITIATES,
                release_at=None,
                reason=RecallHoldReason.OPERATOR_OVERRIDE,
                idempotency_key=f"race-hold-{uuid4().hex}",
            )
        ),
        return_exceptions=True,
    )

    hold_succeeded = any(isinstance(item, RecallHold) for item in results)
    hold_failed = any(isinstance(item, QueueEntryNotSelectable) for item in results)
    assert hold_succeeded != hold_failed, repr(results)
    assert any(isinstance(item, QueueEntry) for item in results), repr(results)

    first_state = _entry_state(admin_conn, first)
    second_state = _entry_state(admin_conn, second)
    active_holds = _active_holds(admin_conn, first)
    if hold_succeeded:
        assert first_state == ("waiting", 2)
        assert second_state[0] == "called"
        assert active_holds == 1
    else:
        assert first_state[0] == "called"
        assert second_state[0] == "waiting"
        assert active_holds == 0


def _entry_state(conn: PgConnection, entry_id: UUID) -> tuple[str, int]:
    row = conn.execute(
        "SELECT status,revision FROM request_engine.queue_entries WHERE id=%s",
        (entry_id,),
    ).fetchone()
    assert row is not None
    return cast(tuple[str, int], row)


def _active_holds(conn: PgConnection, entry_id: UUID) -> int:
    row = conn.execute(
        "SELECT count(*) FROM request_engine.queue_recall_holds "
        "WHERE queue_entry_id=%s AND released_at IS NULL",
        (entry_id,),
    ).fetchone()
    assert row is not None
    return cast(int, row[0])
