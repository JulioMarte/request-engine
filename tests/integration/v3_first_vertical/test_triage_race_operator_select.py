from uuid import uuid4

import pytest

from request_engine.modules.queue.adapters.db.service_queue_commands import (
    PostgresServiceQueueCommands,
)
from request_engine.modules.queue.adapters.db.triage_commands import PostgresQueueTriageCommands
from request_engine.modules.queue.application.commands.call_next import CallNextCommand, call_next
from request_engine.modules.queue.application.commands.triage import OperatorSelectCommand
from request_engine.modules.queue.application.errors import QueueEntryRevisionConflict
from request_engine.modules.queue.contracts.service_queue import QueueEntry
from request_engine.modules.queue.contracts.triage import OperatorSelectReason, QueueTriageResult
from request_engine.platform.db.session import SessionFactory

from .triage_race_support import race_behind_queue_lock
from .triage_scenario import PgConnection, create_world


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_call_next_and_operator_select_call_entry_exactly_once(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    organization_id, principal_id, queue_id, entries = create_world(admin_conn, 1)
    call_result, select_result = await race_behind_queue_lock(
        admin_conn,
        organization_id,
        queue_id,
        call_next(
            PostgresServiceQueueCommands(app_session_factory),
            CallNextCommand(
                organization_id=organization_id,
                principal_id=principal_id,
                queue_id=queue_id,
                idempotency_key=f"call-{uuid4().hex}",
            ),
        ),
        PostgresQueueTriageCommands(app_session_factory).operator_select(
            OperatorSelectCommand(
                organization_id=organization_id,
                principal_id=principal_id,
                queue_entry_id=entries[0],
                reason=OperatorSelectReason.URGENT,
                expected_revision=1,
                idempotency_key=f"select-{uuid4().hex}",
            )
        ),
    )
    state = admin_conn.execute(
        """
        SELECT status, revision FROM request_engine.queue_entries
         WHERE organization_id = %s AND id = %s
        """,
        (organization_id, entries[0]),
    ).fetchone()
    outbox = admin_conn.execute(
        """
        SELECT count(*) FROM request_engine.outbox_messages
         WHERE organization_id = %s AND aggregate_id = %s
           AND event_type = 'queue.entry_called.v1'
        """,
        (organization_id, entries[0]),
    ).fetchone()
    selections = admin_conn.execute(
        """
        SELECT count(*) FROM request_engine.queue_entry_operator_selections
         WHERE organization_id = %s AND queue_entry_id = %s
        """,
        (organization_id, entries[0]),
    ).fetchone()
    assert state == ("called", 2)
    assert outbox == (1,)
    if isinstance(call_result, QueueEntry):
        assert call_result.id == entries[0]
        assert isinstance(select_result, QueueEntryRevisionConflict)
        assert selections == (0,)
    else:
        assert call_result is None
        assert isinstance(select_result, QueueTriageResult)
        assert select_result.queue_entry_id == entries[0]
        assert selections == (1,)
