from uuid import uuid4

import pytest

from request_engine.modules.queue.adapters.db.service_queue_commands import (
    PostgresServiceQueueCommands,
)
from request_engine.modules.queue.adapters.db.triage_commands import PostgresQueueTriageCommands
from request_engine.modules.queue.application.commands.call_next import CallNextCommand, call_next
from request_engine.modules.queue.application.commands.triage import (
    OperatorSelectCommand,
    RecallHoldCommand,
)
from request_engine.modules.queue.contracts.triage import OperatorSelectReason, RecallHoldKind
from request_engine.platform.db.session import SessionFactory

from .triage_scenario import PgConnection, create_world


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_hold_blocks_auto_selection_and_operator_select_releases_it(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    organization_id, principal_id, queue_id, entries = create_world(admin_conn, 2)
    triage = PostgresQueueTriageCommands(app_session_factory)
    held = await triage.recall_hold(
        RecallHoldCommand(
            organization_id=organization_id,
            principal_id=principal_id,
            queue_entry_id=entries[0],
            condition_kind=RecallHoldKind.UNTIL_CUSTOMER_INITIATES,
            expected_revision=1,
            idempotency_key=f"hold-{uuid4().hex}",
            reason="stepped out",
        )
    )
    assert held.revision == 2
    assert held.hold is not None
    auto_called = await call_next(
        PostgresServiceQueueCommands(app_session_factory),
        CallNextCommand(
            organization_id=organization_id,
            principal_id=principal_id,
            queue_id=queue_id,
            idempotency_key=f"call-{uuid4().hex}",
        ),
    )
    assert auto_called is not None
    assert auto_called.id == entries[1]

    key = f"select-{uuid4().hex}"
    command = OperatorSelectCommand(
        organization_id=organization_id,
        principal_id=principal_id,
        queue_entry_id=entries[0],
        reason=OperatorSelectReason.URGENT,
        expected_revision=2,
        idempotency_key=key,
    )
    selected = await triage.operator_select(command)
    replay = await triage.operator_select(command)
    assert replay == selected
    assert selected.status == "called"
    assert selected.revision == 3

    hold_row = admin_conn.execute(
        """
        SELECT release_kind FROM request_engine.queue_entry_recall_holds
         WHERE organization_id = %s AND queue_entry_id = %s
        """,
        (organization_id, entries[0]),
    ).fetchone()
    selection_count = admin_conn.execute(
        """
        SELECT count(*) FROM request_engine.queue_entry_operator_selections
         WHERE organization_id = %s AND queue_entry_id = %s
        """,
        (organization_id, entries[0]),
    ).fetchone()
    outbox_count = admin_conn.execute(
        """
        SELECT count(*) FROM request_engine.outbox_messages
         WHERE organization_id = %s AND aggregate_id = %s
           AND event_type = 'queue.entry_called.v1'
        """,
        (organization_id, entries[0]),
    ).fetchone()
    assert hold_row == ("operator_select",)
    assert selection_count == (1,)
    assert outbox_count == (1,)
