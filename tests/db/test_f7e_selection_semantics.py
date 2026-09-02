from uuid import uuid4

import pytest

from f7e_selection_assertions import call_next_command, entry_state
from f7e_selection_fixture import PgConnection, create_f7e_selection_fixture
from request_engine.modules.queue.adapters.db.same_day_selection_commands import (
    PostgresSameDaySelectionCommands,
)
from request_engine.modules.queue.adapters.db.service_queue_commands import (
    PostgresServiceQueueCommands,
)
from request_engine.modules.queue.application.commands.recall_hold import RecallHoldCommand
from request_engine.modules.queue.application.commands.release_recall_hold import (
    ReleaseRecallHoldCommand,
)
from request_engine.modules.queue.application.commands.skip_queue_head import SkipQueueHeadCommand
from request_engine.modules.queue.contracts.same_day_selection import RecallHoldKind, SkipReason
from request_engine.platform.db.session import SessionFactory

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.mark.asyncio
async def test_recall_hold_blocks_fifo_until_explicit_release(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    world = create_f7e_selection_fixture(admin_conn)
    first, second, _third = world.entry_ids
    f7e = PostgresSameDaySelectionCommands(command_session_factory)
    queue = PostgresServiceQueueCommands(command_session_factory)

    await f7e.recall_hold(
        RecallHoldCommand(
            organization_id=world.organization_id,
            principal_id=world.principal_id,
            queue_id=world.queue_id,
            queue_entry_id=first,
            expected_revision=1,
            kind=RecallHoldKind.UNTIL_CUSTOMER_INITIATES,
            release_at=None,
            reason="patient stepped outside",
            idempotency_key=f"hold-{uuid4().hex}",
        )
    )
    called = await queue.call_next(call_next_command(world, "while-held"))
    assert called is not None and called.id == second

    await f7e.release_recall_hold(
        ReleaseRecallHoldCommand(
            organization_id=world.organization_id,
            principal_id=world.principal_id,
            queue_id=world.queue_id,
            queue_entry_id=first,
            idempotency_key=f"release-{uuid4().hex}",
        )
    )
    recalled = await queue.call_next(call_next_command(world, "after-release"))
    assert recalled is not None and recalled.id == first


@pytest.mark.asyncio
async def test_skip_bypasses_head_once_without_reordering(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    world = create_f7e_selection_fixture(admin_conn)
    first, second, _third = world.entry_ids
    f7e = PostgresSameDaySelectionCommands(command_session_factory)
    queue = PostgresServiceQueueCommands(command_session_factory)
    state_before = entry_state(admin_conn, first)

    skipped = await f7e.skip_queue_head(
        SkipQueueHeadCommand(
            organization_id=world.organization_id,
            principal_id=world.principal_id,
            queue_id=world.queue_id,
            reason=SkipReason.NO_RESPONSE,
            idempotency_key=f"skip-{uuid4().hex}",
        )
    )
    assert skipped is not None
    assert skipped.skipped_entry_id == first
    assert skipped.called_entry is not None and skipped.called_entry.id == second
    assert entry_state(admin_conn, first) == state_before

    next_called = await queue.call_next(call_next_command(world, "after-skip"))
    assert next_called is not None and next_called.id == first
