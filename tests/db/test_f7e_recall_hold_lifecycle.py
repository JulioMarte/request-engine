from datetime import timedelta
from uuid import UUID, uuid4

import pytest

from f7e_selection_assertions import call_next_command
from f7e_selection_fixture import (
    F7eSelectionFixture,
    PgConnection,
    create_f7e_selection_fixture,
)
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
from request_engine.modules.queue.application.errors import QueueEntryRevisionConflict
from request_engine.modules.queue.contracts.same_day_selection import (
    RecallHoldKind,
    RecallHoldReason,
)
from request_engine.platform.db.session import SessionFactory

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.mark.asyncio
async def test_until_time_expires_from_database_clock_without_release_worker(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    world = create_f7e_selection_fixture(admin_conn)
    first, second, _third = world.entry_ids
    now_row = admin_conn.execute("SELECT clock_timestamp()").fetchone()
    assert now_row is not None
    release_at = now_row[0] + timedelta(seconds=3)
    f7e = PostgresSameDaySelectionCommands(command_session_factory)
    queue = PostgresServiceQueueCommands(command_session_factory)

    hold = await f7e.recall_hold(
        RecallHoldCommand(
            organization_id=world.organization_id,
            principal_id=world.principal_id,
            queue_id=world.queue_id,
            queue_entry_id=first,
            expected_revision=1,
            kind=RecallHoldKind.UNTIL_TIME,
            release_at=release_at,
            reason=RecallHoldReason.TEMPORARILY_UNAVAILABLE,
            idempotency_key=f"timed-hold-{uuid4().hex}",
        )
    )
    called_while_held = await queue.call_next(call_next_command(world, "timed-held"))
    assert called_while_held is not None and called_while_held.id == second

    admin_conn.execute("SELECT pg_sleep(3.1)")
    called_after_expiry = await queue.call_next(call_next_command(world, "timed-expired"))
    assert called_after_expiry is not None and called_after_expiry.id == first
    released_at = admin_conn.execute(
        "SELECT released_at FROM request_engine.queue_recall_holds WHERE id=%s",
        (hold.id,),
    ).fetchone()
    assert released_at == (None,)


@pytest.mark.asyncio
async def test_stale_hold_commands_cannot_replace_or_release_newer_intent(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    world = create_f7e_selection_fixture(admin_conn)
    first = world.entry_ids[0]
    commands = PostgresSameDaySelectionCommands(command_session_factory)
    first_hold = await commands.recall_hold(_customer_hold(world, first, 1, "first"))

    with pytest.raises(QueueEntryRevisionConflict):
        await commands.recall_hold(_customer_hold(world, first, 1, "stale-replace"))

    second_hold = await commands.recall_hold(
        _customer_hold(world, first, first_hold.queue_entry_revision, "replacement")
    )
    with pytest.raises(QueueEntryRevisionConflict):
        await commands.release_recall_hold(
            ReleaseRecallHoldCommand(
                organization_id=world.organization_id,
                principal_id=world.principal_id,
                queue_id=world.queue_id,
                queue_entry_id=first,
                hold_id=first_hold.id,
                expected_revision=first_hold.queue_entry_revision,
                idempotency_key=f"stale-release-{uuid4().hex}",
            )
        )
    assert second_hold.queue_entry_revision == first_hold.queue_entry_revision + 1


def _customer_hold(
    world: F7eSelectionFixture,
    entry_id: UUID,
    revision: int,
    suffix: str,
) -> RecallHoldCommand:
    return RecallHoldCommand(
        organization_id=world.organization_id,
        principal_id=world.principal_id,
        queue_id=world.queue_id,
        queue_entry_id=entry_id,
        expected_revision=revision,
        kind=RecallHoldKind.UNTIL_CUSTOMER_INITIATES,
        release_at=None,
        reason=RecallHoldReason.OPERATOR_OVERRIDE,
        idempotency_key=f"hold-{suffix}-{uuid4().hex}",
    )
