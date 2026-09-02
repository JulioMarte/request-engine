import asyncio
from uuid import UUID, uuid4

import pytest
from f7e_selection_fixture import F7eSelectionFixture, PgConnection, create_f7e_selection_fixture
from f7e_selection_race_barrier import AsyncTwoPartyBarrier, gated_lock

from request_engine.modules.queue.adapters.db import recall_hold as recall_hold_module
from request_engine.modules.queue.adapters.db.same_day_selection_commands import (
    PostgresSameDaySelectionCommands,
)
from request_engine.modules.queue.application.commands.recall_hold import RecallHoldCommand
from request_engine.modules.queue.application.errors import QueueEntryRevisionConflict
from request_engine.modules.queue.contracts.same_day_selection import (
    RecallHold,
    RecallHoldKind,
    RecallHoldReason,
)
from request_engine.platform.db.session import SessionFactory

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.mark.asyncio
async def test_concurrent_recall_holds_create_exactly_one_current_hold(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = create_f7e_selection_fixture(admin_conn)
    first = world.entry_ids[0]
    barrier = AsyncTwoPartyBarrier()
    original_lock = recall_hold_module.lock_active_queue
    monkeypatch.setattr(
        recall_hold_module,
        "lock_active_queue",
        gated_lock(barrier, original_lock),
    )
    commands = PostgresSameDaySelectionCommands(command_session_factory)

    results = await asyncio.gather(
        commands.recall_hold(_hold_command(world, first, "a")),
        commands.recall_hold(_hold_command(world, first, "b")),
        return_exceptions=True,
    )

    assert sum(isinstance(item, RecallHold) for item in results) == 1, repr(results)
    assert sum(isinstance(item, QueueEntryRevisionConflict) for item in results) == 1, repr(results)
    row = admin_conn.execute(
        "SELECT count(*), min(hold_kind), max(hold_kind) "
        "FROM request_engine.queue_recall_holds "
        "WHERE organization_id=%s AND queue_entry_id=%s AND released_at IS NULL",
        (world.organization_id, first),
    ).fetchone()
    assert row == (1, "until_customer_initiates", "until_customer_initiates")
    revision = admin_conn.execute(
        "SELECT revision FROM request_engine.queue_entries WHERE id=%s",
        (first,),
    ).fetchone()
    assert revision == (2,)


def _hold_command(
    world: F7eSelectionFixture,
    entry_id: UUID,
    suffix: str,
) -> RecallHoldCommand:
    return RecallHoldCommand(
        organization_id=world.organization_id,
        principal_id=world.principal_id,
        queue_id=world.queue_id,
        queue_entry_id=entry_id,
        expected_revision=1,
        kind=RecallHoldKind.UNTIL_CUSTOMER_INITIATES,
        release_at=None,
        reason=RecallHoldReason.OPERATOR_OVERRIDE,
        idempotency_key=f"hold-race-{suffix}-{uuid4().hex}",
    )
