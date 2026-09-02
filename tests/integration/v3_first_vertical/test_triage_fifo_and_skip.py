from uuid import uuid4

import pytest

from request_engine.modules.queue.adapters.db.service_queue_commands import (
    PostgresServiceQueueCommands,
)
from request_engine.modules.queue.adapters.db.triage_commands import PostgresQueueTriageCommands
from request_engine.modules.queue.application.commands.call_next import CallNextCommand, call_next
from request_engine.modules.queue.application.commands.triage import SkipCommand
from request_engine.modules.queue.contracts.service_queue import QueueEntryStatus
from request_engine.modules.queue.contracts.triage import SkipReason
from request_engine.platform.db.session import SessionFactory

from .triage_scenario import PgConnection, create_world


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_call_next_without_triage_preserves_fifo(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    organization_id, principal_id, queue_id, entries = create_world(admin_conn, 2)
    result = await call_next(
        PostgresServiceQueueCommands(app_session_factory),
        CallNextCommand(
            organization_id=organization_id,
            principal_id=principal_id,
            queue_id=queue_id,
            idempotency_key=f"call-{uuid4().hex}",
        ),
    )
    assert result is not None
    assert result.id == entries[0]
    assert result.status is QueueEntryStatus.CALLED
    assert result.revision == 2
    assert result.admitted_at.isoformat() == "2026-09-02T10:00:00+00:00"


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_skip_defers_exactly_one_selection_without_rewriting_arrival_order(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    organization_id, principal_id, queue_id, entries = create_world(admin_conn, 2)
    triage = PostgresQueueTriageCommands(app_session_factory)
    service = PostgresServiceQueueCommands(app_session_factory)
    skipped = await triage.skip(
        SkipCommand(
            organization_id=organization_id,
            principal_id=principal_id,
            queue_entry_id=entries[0],
            reason=SkipReason.NO_RESPONSE,
            expected_revision=1,
            idempotency_key=f"skip-{uuid4().hex}",
        )
    )
    assert skipped.revision == 2
    first_called = await call_next(
        service,
        CallNextCommand(
            organization_id=organization_id,
            principal_id=principal_id,
            queue_id=queue_id,
            idempotency_key=f"call-{uuid4().hex}",
        ),
    )
    assert first_called is not None
    assert first_called.id == entries[1]
    skip_row = admin_conn.execute(
        """
        SELECT consumed_by_entry_id
          FROM request_engine.queue_entry_skips
         WHERE organization_id = %s AND queue_entry_id = %s
        """,
        (organization_id, entries[0]),
    ).fetchone()
    entry_row = admin_conn.execute(
        """
        SELECT admitted_at, revision
          FROM request_engine.queue_entries
         WHERE organization_id = %s AND id = %s
        """,
        (organization_id, entries[0]),
    ).fetchone()
    assert skip_row == (entries[1],)
    assert entry_row is not None
    assert entry_row[0].isoformat() == "2026-09-02T10:00:00+00:00"
    assert entry_row[1] == 3
    second_called = await call_next(
        service,
        CallNextCommand(
            organization_id=organization_id,
            principal_id=principal_id,
            queue_id=queue_id,
            idempotency_key=f"call-{uuid4().hex}",
        ),
    )
    assert second_called is not None
    assert second_called.id == entries[0]
    assert second_called.revision == 4
