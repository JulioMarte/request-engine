from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from f7e_selection_fixture import PgConnection, create_f7e_selection_fixture

from request_engine.modules.queue.adapters.db.live_capacity_recall_hold import (
    has_active_recall_hold,
)
from request_engine.modules.queue.adapters.db.same_day_selection_commands import (
    PostgresSameDaySelectionCommands,
)
from request_engine.modules.queue.application.commands.recall_hold import RecallHoldCommand
from request_engine.modules.queue.contracts.same_day_selection import (
    RecallHoldKind,
    RecallHoldReason,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.mark.asyncio
async def test_projection_hold_source_ignores_hold_after_entry_leaves_waiting(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    world = create_f7e_selection_fixture(admin_conn)
    first = world.entry_ids[0]
    commands = PostgresSameDaySelectionCommands(command_session_factory)
    await commands.recall_hold(
        RecallHoldCommand(
            organization_id=world.organization_id,
            principal_id=world.principal_id,
            queue_id=world.queue_id,
            queue_entry_id=first,
            expected_revision=1,
            kind=RecallHoldKind.UNTIL_CUSTOMER_INITIATES,
            release_at=None,
            reason=RecallHoldReason.OPERATOR_OVERRIDE,
            idempotency_key=f"projection-hold-{uuid4().hex}",
        )
    )
    observed = datetime(2035, 1, 1, 9, 0, tzinfo=UTC)
    assert await _has_hold(command_session_factory, world.organization_id, world.queue_id, observed)

    admin_conn.execute(
        "UPDATE request_engine.queue_entries "
        "SET status='cancelled', revision=revision+1, updated_at=clock_timestamp() "
        "WHERE organization_id=%s AND id=%s",
        (world.organization_id, first),
    )
    assert not await _has_hold(
        command_session_factory,
        world.organization_id,
        world.queue_id,
        observed,
    )
    row = admin_conn.execute(
        "SELECT released_at FROM request_engine.queue_recall_holds WHERE queue_entry_id=%s",
        (first,),
    ).fetchone()
    assert row == (None,)


async def _has_hold(
    session_factory: SessionFactory,
    organization_id: UUID,
    queue_id: UUID,
    observed_at: datetime,
) -> bool:
    async with tenant_transaction(session_factory, organization_id) as session:
        return await has_active_recall_hold(
            session,
            organization_id=organization_id,
            queue_id=queue_id,
            observed_at=observed_at,
        )
