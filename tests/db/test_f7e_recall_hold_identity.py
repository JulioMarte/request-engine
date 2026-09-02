from uuid import UUID, uuid4

import pytest

from f7e_selection_fixture import (
    F7eSelectionFixture,
    PgConnection,
    create_f7e_selection_fixture,
)
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
    assert _current_hold(admin_conn, world, first) == (current.id, None)
    revision = admin_conn.execute(
        "SELECT revision FROM request_engine.queue_entries WHERE id=%s", (first,)
    ).fetchone()
    assert revision == (current.queue_entry_revision,)
    assert _count(
        admin_conn,
        "SELECT count(*) FROM request_engine.idempotency_records "
        "WHERE organization_id=%s AND principal_id=%s AND idempotency_key=%s",
        (world.organization_id, world.principal_id, key),
    ) == 0
    assert _count(
        admin_conn,
        "SELECT count(*) FROM request_engine.audit_records "
        "WHERE organization_id=%s AND command_name='queue.release_recall_hold'",
        (world.organization_id,),
    ) == 0
    assert _count(
        admin_conn,
        "SELECT count(*) FROM request_engine.outbox_messages "
        "WHERE organization_id=%s AND event_type='queue.recall_hold_released.v1'",
        (world.organization_id,),
    ) == 0


def _hold(
    world: F7eSelectionFixture,
    entry_id: UUID,
    revision: int,
    suffix: str,
) -> RecallHoldCommand:
    return RecallHoldCommand(
        world.organization_id,
        world.principal_id,
        world.queue_id,
        entry_id,
        revision,
        RecallHoldKind.UNTIL_CUSTOMER_INITIATES,
        None,
        RecallHoldReason.OPERATOR_OVERRIDE,
        f"identity-hold-{suffix}-{uuid4().hex}",
    )


def _current_hold(
    conn: PgConnection,
    world: F7eSelectionFixture,
    entry_id: UUID,
) -> tuple[UUID, object] | None:
    return conn.execute(
        "SELECT id,released_at FROM request_engine.queue_recall_holds "
        "WHERE organization_id=%s AND queue_entry_id=%s AND released_at IS NULL",
        (world.organization_id, entry_id),
    ).fetchone()


def _count(conn: PgConnection, sql: str, params: tuple[object, ...]) -> int:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return int(row[0])
