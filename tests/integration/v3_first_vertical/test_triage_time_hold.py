from uuid import uuid4

import pytest

from request_engine.modules.queue.adapters.db.service_queue_commands import (
    PostgresServiceQueueCommands,
)
from request_engine.modules.queue.application.commands.call_next import CallNextCommand, call_next
from request_engine.platform.db.session import SessionFactory

from .triage_scenario import PgConnection, create_world


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_expired_time_hold_is_released_before_fifo_selection(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    organization_id, principal_id, queue_id, entries = create_world(admin_conn, 1)
    admin_conn.execute(
        """
        INSERT INTO request_engine.queue_entry_recall_holds (
            organization_id, queue_entry_id, condition_kind,
            until_at, created_by_principal_id
        ) VALUES (%s, %s, 'until_time', clock_timestamp() - interval '1 minute', %s)
        """,
        (organization_id, entries[0], principal_id),
    )
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
    released = admin_conn.execute(
        """
        SELECT release_kind FROM request_engine.queue_entry_recall_holds
         WHERE organization_id = %s AND queue_entry_id = %s
        """,
        (organization_id, entries[0]),
    ).fetchone()
    assert released == ("expired",)
