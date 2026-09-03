from uuid import uuid4

import pytest

from request_engine.modules.queue.adapters.db.service_queue_commands import (
    PostgresServiceQueueCommands,
)
from request_engine.modules.queue.adapters.db.triage_commands import PostgresQueueTriageCommands
from request_engine.modules.queue.application.commands.call_next import CallNextCommand, call_next
from request_engine.modules.queue.application.commands.triage import SkipCommand
from request_engine.modules.queue.application.errors import QueueEntryRevisionConflict
from request_engine.modules.queue.contracts.service_queue import QueueEntry
from request_engine.modules.queue.contracts.triage import QueueTriageResult, SkipReason
from request_engine.platform.db.session import SessionFactory

from .triage_race_support import race_behind_queue_lock
from .triage_scenario import PgConnection, create_world


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_call_next_and_skip_serialize_on_same_queue_lock(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    organization_id, principal_id, queue_id, entries = create_world(admin_conn, 2)
    call_result, skip_result = await race_behind_queue_lock(
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
        PostgresQueueTriageCommands(app_session_factory).skip(
            SkipCommand(
                organization_id=organization_id,
                principal_id=principal_id,
                queue_entry_id=entries[0],
                reason=SkipReason.NO_RESPONSE,
                expected_revision=1,
                idempotency_key=f"skip-{uuid4().hex}",
            )
        ),
    )
    rows = admin_conn.execute(
        """
        SELECT id, status, revision FROM request_engine.queue_entries
         WHERE organization_id = %s AND service_queue_id = %s
         ORDER BY admitted_at, id
        """,
        (organization_id, queue_id),
    ).fetchall()
    skip_row = admin_conn.execute(
        """
        SELECT consumed_by_entry_id FROM request_engine.queue_entry_skips
         WHERE organization_id = %s AND queue_entry_id = %s
        """,
        (organization_id, entries[0]),
    ).fetchone()
    outbox = admin_conn.execute(
        """
        SELECT aggregate_id FROM request_engine.outbox_messages
         WHERE organization_id = %s AND event_type = 'queue.entry_called.v1'
        """,
        (organization_id,),
    ).fetchall()
    assert len(outbox) == 1
    if rows[0][1] == "called":
        assert rows[0][0] == entries[0]
        assert isinstance(call_result, QueueEntry)
        assert isinstance(skip_result, QueueEntryRevisionConflict)
        assert skip_row is None
        assert outbox == [(entries[0],)]
    else:
        assert rows[0] == (entries[0], "waiting", 3)
        assert rows[1][0:2] == (entries[1], "called")
        assert isinstance(call_result, QueueEntry)
        assert call_result.id == entries[1]
        assert isinstance(skip_result, QueueTriageResult)
        assert skip_row == (entries[1],)
        assert outbox == [(entries[1],)]
