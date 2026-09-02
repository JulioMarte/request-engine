from uuid import uuid4

import pytest

from f7e_selection_fixture import PgConnection, create_f7e_selection_fixture
from request_engine.modules.queue.adapters.db.same_day_selection_commands import (
    PostgresSameDaySelectionCommands,
)
from request_engine.modules.queue.application.commands.recall_hold import RecallHoldCommand
from request_engine.modules.queue.application.commands.release_recall_hold import (
    ReleaseRecallHoldCommand,
)
from request_engine.modules.queue.application.same_day_selection_errors import RecallHoldConflict
from request_engine.modules.queue.contracts.same_day_selection import RecallHoldKind, RecallHoldReason
from request_engine.platform.db.session import SessionFactory

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.mark.asyncio
async def test_old_hold_id_cannot_release_new_current_hold(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    world = create_f7e_selection_fixture(admin_conn)
    first = world.entry_ids[0]
    commands = PostgresSameDaySelectionCommands(command_session_factory)
    old = await commands.recall_hold(_hold(world, first, 1, "old"))
    current = await commands.recall_hold(
        _hold(world, first, old.queue_entry_revision, "current")
    )
    key = f"wrong-hold-release-{uuid4().hex}"

    with pytest.raises(RecallHoldConflict) as raised:
        await commands.release_recall_hold(
            ReleaseRecallHoldCommand(
                organization_id=world.organization_id,
                principal_id=world.principal_id,
                queue_id=world.queue_id,
                queue_entry_id=first,
                hold_id=old.id,
                expected_revision=current.queue_entry_revision,
                idempotency_key=key,
            )
        )

    assert raised.value.active_hold_id == current.id
    row = admin_conn.execute(
        "SELECT id,released_at FROM request_engine.queue_recall_holds "
        "WHERE organization_id=%s AND queue_entry_id=%s AND released_at IS NULL",
        (world.organization_id, first),
    ).fetchone()
    assert row == (current.id, None)
    revision = admin_conn.execute(
        "SELECT revision FROM request_engine.queue_entries WHERE id=%s", (first,)
    ).fetchone()
    assert revision == (current.queue_entry_revision,)
    effects = admin_conn.execute(
        "SELECT count(*) FROM request_engine.idempotency_records "
        "WHERE organization_id=%s AND principal_id=%s AND idempotency_key=%s",
        (world.organization_id, world.principal_id, key),
    ).fetchone()
    assert effects == (0,)


def _hold(world, entry_id, revision: int, suffix: str) -> RecallHoldCommand:
    return RecallHoldCommand(
        organization_id=world.organization_id,
        principal_id=world.principal_id,
        queue_id=world.queue_id,
        queue_entry_id=entry_id,
        expected_revision=revision,
        kind=RecallHoldKind.UNTIL_CUSTOMER_INITIATES,
        release_at=None,
        reason=RecallHoldReason.OPERATOR_OVERRIDE,
        idempotency_key=f"identity-hold-{suffix}-{uuid4().hex}",
    )
