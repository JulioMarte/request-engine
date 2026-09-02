from uuid import uuid4

import pytest

from request_engine.modules.queue.adapters.db.service_queue_commands import (
    PostgresServiceQueueCommands,
)
from request_engine.modules.queue.adapters.db.triage_commands import PostgresQueueTriageCommands
from request_engine.modules.queue.application.commands.call_next import CallNextCommand, call_next
from request_engine.modules.queue.application.commands.triage import RecallHoldCommand
from request_engine.modules.queue.application.errors import QueueEntryRevisionConflict
from request_engine.modules.queue.contracts.service_queue import QueueEntry
from request_engine.modules.queue.contracts.triage import QueueTriageResult, RecallHoldKind
from request_engine.platform.db.session import SessionFactory

from .triage_race_support import race_behind_queue_lock
from .triage_scenario import PgConnection, create_world


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_call_next_and_recall_hold_serialize_without_lost_hold(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    organization_id, principal_id, queue_id, entries = create_world(admin_conn, 1)
    call_result, hold_result = await race_behind_queue_lock(
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
        PostgresQueueTriageCommands(app_session_factory).recall_hold(
            RecallHoldCommand(
                organization_id=organization_id,
                principal_id=principal_id,
                queue_entry_id=entries[0],
                condition_kind=RecallHoldKind.UNTIL_CUSTOMER_INITIATES,
                expected_revision=1,
                idempotency_key=f"hold-{uuid4().hex}",
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
    active_holds = admin_conn.execute(
        """
        SELECT count(*) FROM request_engine.queue_entry_recall_holds
         WHERE organization_id = %s AND queue_entry_id = %s AND released_at IS NULL
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
    assert state is not None
    if state[0] == "waiting":
        assert call_result is None
        assert isinstance(hold_result, QueueTriageResult)
        assert active_holds == (1,)
        assert outbox == (0,)
    else:
        assert state == ("called", 2)
        assert isinstance(call_result, QueueEntry)
        assert isinstance(hold_result, QueueEntryRevisionConflict)
        assert active_holds == (0,)
        assert outbox == (1,)
