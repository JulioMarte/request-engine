from uuid import uuid4

import pytest

from f7e_selection_fixture import PgConnection, create_f7e_selection_fixture
from request_engine.modules.queue.adapters.db.live_queue_reader import PostgresLiveQueueReader
from request_engine.modules.queue.adapters.db.same_day_selection_commands import (
    PostgresSameDaySelectionCommands,
)
from request_engine.modules.queue.application.commands.recall_hold import RecallHoldCommand
from request_engine.modules.queue.application.commands.release_recall_hold import (
    ReleaseRecallHoldCommand,
)
from request_engine.modules.queue.contracts.same_day_selection import RecallHoldKind
from request_engine.platform.db.session import SessionFactory

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.mark.asyncio
async def test_staff_read_exposes_active_recall_hold_and_clears_after_release(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    world = create_f7e_selection_fixture(admin_conn)
    first = world.entry_ids[0]
    commands = PostgresSameDaySelectionCommands(command_session_factory)
    reader = PostgresLiveQueueReader(command_session_factory)

    hold = await commands.recall_hold(
        RecallHoldCommand(
            organization_id=world.organization_id,
            principal_id=world.principal_id,
            queue_id=world.queue_id,
            queue_entry_id=first,
            expected_revision=1,
            kind=RecallHoldKind.UNTIL_CUSTOMER_INITIATES,
            release_at=None,
            reason="patient stepped outside",
            idempotency_key=f"staff-hold-{uuid4().hex}",
        )
    )
    held_entries = await reader.staff_queue(world.organization_id, world.queue_id)
    held = next(item for item in held_entries if item.queue_entry_id == first)
    assert held.recall_hold_kind == "until_customer_initiates"
    assert held.recall_hold_release_at is None
    assert held.queue_revision == hold.queue_entry_revision

    await commands.release_recall_hold(
        ReleaseRecallHoldCommand(
            organization_id=world.organization_id,
            principal_id=world.principal_id,
            queue_id=world.queue_id,
            queue_entry_id=first,
            hold_id=hold.id,
            expected_revision=hold.queue_entry_revision,
            idempotency_key=f"staff-release-{uuid4().hex}",
        )
    )
    released_entries = await reader.staff_queue(world.organization_id, world.queue_id)
    released = next(item for item in released_entries if item.queue_entry_id == first)
    assert released.recall_hold_kind is None
    assert released.recall_hold_release_at is None
