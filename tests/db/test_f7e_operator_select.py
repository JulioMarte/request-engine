from uuid import uuid4

import pytest

from f7e_selection_assertions import entry_status
from f7e_selection_fixture import PgConnection, create_f7e_selection_fixture
from request_engine.modules.queue.adapters.db.same_day_selection_commands import (
    PostgresSameDaySelectionCommands,
)
from request_engine.modules.queue.application.commands.operator_select import OperatorSelectCommand
from request_engine.modules.queue.application.commands.recall_hold import RecallHoldCommand
from request_engine.modules.queue.application.same_day_selection_errors import QueueEntryRecallHeld
from request_engine.modules.queue.contracts.same_day_selection import (
    OperatorSelectReason,
    RecallHoldKind,
    RecallHoldReason,
)
from request_engine.platform.db.session import SessionFactory

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.mark.asyncio
async def test_operator_select_calls_target_without_rewriting_fifo(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    world = create_f7e_selection_fixture(admin_conn)
    first, second, third = world.entry_ids
    commands = PostgresSameDaySelectionCommands(command_session_factory)

    selected = await commands.operator_select(
        OperatorSelectCommand(
            organization_id=world.organization_id,
            principal_id=world.principal_id,
            queue_id=world.queue_id,
            queue_entry_id=third,
            expected_revision=1,
            reason=OperatorSelectReason.URGENT_OPERATIONAL_NEED,
            idempotency_key=f"select-{uuid4().hex}",
        )
    )

    assert selected.id == third
    assert entry_status(admin_conn, first) == "waiting"
    assert entry_status(admin_conn, second) == "waiting"
    fact = admin_conn.execute(
        "SELECT selection_kind,reason FROM request_engine.queue_selection_facts "
        "WHERE organization_id=%s AND queue_entry_id=%s",
        (world.organization_id, third),
    ).fetchone()
    assert fact == ("operator_select", "urgent_operational_need")


@pytest.mark.asyncio
async def test_operator_select_refuses_active_recall_hold_without_call_effects(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    world = create_f7e_selection_fixture(admin_conn)
    first = world.entry_ids[0]
    commands = PostgresSameDaySelectionCommands(command_session_factory)
    hold = await commands.recall_hold(
        RecallHoldCommand(
            world.organization_id,
            world.principal_id,
            world.queue_id,
            first,
            1,
            RecallHoldKind.UNTIL_CUSTOMER_INITIATES,
            None,
            RecallHoldReason.STEPPED_AWAY,
            f"select-held-setup-{uuid4().hex}",
        )
    )

    with pytest.raises(QueueEntryRecallHeld):
        await commands.operator_select(
            OperatorSelectCommand(
                world.organization_id,
                world.principal_id,
                world.queue_id,
                first,
                hold.queue_entry_revision,
                OperatorSelectReason.OPERATOR_OVERRIDE,
                f"select-held-{uuid4().hex}",
            )
        )

    assert entry_status(admin_conn, first) == "waiting"
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.queue_selection_facts "
        "WHERE organization_id=%s AND queue_entry_id=%s",
        (world.organization_id, first),
    ).fetchone() == (0,)
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.outbox_messages "
        "WHERE organization_id=%s AND event_type='queue.entry_called.v1'",
        (world.organization_id,),
    ).fetchone() == (0,)
