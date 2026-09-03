from typing import cast
from uuid import UUID, uuid4

import pytest

from request_engine.modules.queue.adapters.db.service_queue_reader import PostgresServiceQueueReader
from request_engine.modules.queue.adapters.db.triage_commands import PostgresQueueTriageCommands
from request_engine.modules.queue.application.commands.triage import RecallHoldCommand, SkipCommand
from request_engine.modules.queue.contracts.triage import RecallHoldKind, SkipReason
from request_engine.platform.db.session import SessionFactory

from .triage_scenario import PgConnection, create_world


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_entries_ahead_counts_only_entries_eligible_for_next_recall(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    organization_id, principal_id, queue_id, entries = create_world(admin_conn, 3)
    triage = PostgresQueueTriageCommands(app_session_factory)

    await triage.skip(
        SkipCommand(
            organization_id=organization_id,
            principal_id=principal_id,
            queue_entry_id=entries[0],
            reason=SkipReason.TEMPORARILY_UNAVAILABLE,
            expected_revision=1,
            idempotency_key=f"skip-{uuid4().hex}",
        )
    )
    await triage.recall_hold(
        RecallHoldCommand(
            organization_id=organization_id,
            principal_id=principal_id,
            queue_entry_id=entries[1],
            condition_kind=RecallHoldKind.UNTIL_EVENT,
            event_key="external_step_completed",
            expected_revision=1,
            idempotency_key=f"hold-{uuid4().hex}",
            reason="external prerequisite pending",
        )
    )

    row = admin_conn.execute(
        """
        SELECT subject_party_id
          FROM request_engine.queue_entries
         WHERE organization_id = %s AND id = %s
        """,
        (organization_id, entries[2]),
    ).fetchone()
    assert row is not None
    subject_party_id = cast(UUID, row[0])

    status = await PostgresServiceQueueReader(app_session_factory).get_queue_status(
        organization_id,
        principal_id,
        queue_id,
        subject_party_id,
        allow_subject_override=True,
    )

    assert status.entry is not None
    assert status.entry.id == entries[2]
    assert status.entries_ahead == 0
