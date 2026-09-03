import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from request_engine.modules.queue.adapters.db.service_queue_commands import (
    PostgresServiceQueueCommands,
)
from request_engine.modules.queue.adapters.db.triage_commands import PostgresQueueTriageCommands
from request_engine.modules.queue.application.commands.call_next import CallNextCommand, call_next
from request_engine.modules.queue.application.commands.triage import (
    OperatorSelectCommand,
    RecallHoldCommand,
    ReleaseRecallHoldCommand,
)
from request_engine.modules.queue.application.errors import QueueEntryRevisionConflict
from request_engine.modules.queue.application.triage_errors import (
    QueueEntryNotWaiting,
    QueueHoldNotActive,
    RecallHoldConflict,
)
from request_engine.modules.queue.contracts.triage import OperatorSelectReason, RecallHoldKind
from request_engine.platform.db.session import SessionFactory

from .triage_scenario import PgConnection, create_world


def release_command(
    organization_id: UUID,
    principal_id: UUID,
    entry_id: UUID,
    hold_id: UUID,
    expected_revision: int,
) -> ReleaseRecallHoldCommand:
    return ReleaseRecallHoldCommand(
        organization_id=organization_id,
        principal_id=principal_id,
        queue_entry_id=entry_id,
        hold_id=hold_id,
        expected_revision=expected_revision,
        idempotency_key=f"release-{uuid4().hex}",
    )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_release_returns_entry_to_original_fifo_position_without_calling_it(
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
    assert held.hold is not None

    released = await triage.release_recall_hold(
        release_command(organization_id, principal_id, entries[0], held.hold.id, 2)
    )
    assert released.status == "waiting"
    assert released.revision == 3
    assert released.action == "release_recall_hold"
    assert released.hold is None

    row = admin_conn.execute(
        """
        SELECT release_kind, released_at FROM request_engine.queue_entry_recall_holds
         WHERE organization_id = %s AND queue_entry_id = %s
        """,
        (organization_id, entries[0]),
    ).fetchone()
    assert row is not None and row[0] == "operator_release" and row[1] is not None

    audit = admin_conn.execute(
        """
        SELECT count(*) FROM request_engine.audit_records
         WHERE organization_id = %s AND command_name = 'queue.release_recall_hold'
        """,
        (organization_id,),
    ).fetchone()
    assert audit == (1,)

    outbox = admin_conn.execute(
        """
        SELECT count(*) FROM request_engine.outbox_messages
         WHERE organization_id = %s AND aggregate_id = %s
        """,
        (organization_id, entries[0]),
    ).fetchone()
    assert outbox == (0,)

    admitted = admin_conn.execute(
        """
        SELECT admitted_at FROM request_engine.queue_entries
         WHERE organization_id = %s AND id = %s
        """,
        (organization_id, entries[0]),
    ).fetchone()
    assert admitted is not None

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
    assert auto_called.id == entries[0]


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_release_replays_the_recorded_result_for_the_same_idempotency_key(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    organization_id, principal_id, _queue_id, entries = create_world(admin_conn, 1)
    triage = PostgresQueueTriageCommands(app_session_factory)
    held = await triage.recall_hold(
        RecallHoldCommand(
            organization_id=organization_id,
            principal_id=principal_id,
            queue_entry_id=entries[0],
            condition_kind=RecallHoldKind.UNTIL_EVENT,
            event_key="external_step_completed",
            expected_revision=1,
            idempotency_key=f"hold-{uuid4().hex}",
        )
    )
    assert held.hold is not None
    command = ReleaseRecallHoldCommand(
        organization_id=organization_id,
        principal_id=principal_id,
        queue_entry_id=entries[0],
        hold_id=held.hold.id,
        expected_revision=2,
        idempotency_key=f"release-{uuid4().hex}",
    )
    released = await triage.release_recall_hold(command)
    replay = await triage.release_recall_hold(command)
    assert replay == released
    assert replay.revision == 3


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_release_fails_closed_on_stale_screen_worlds(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    organization_id, principal_id, _queue_id, entries = create_world(admin_conn, 1)
    triage = PostgresQueueTriageCommands(app_session_factory)

    with pytest.raises(QueueHoldNotActive):
        await triage.release_recall_hold(
            release_command(organization_id, principal_id, entries[0], uuid4(), 1)
        )

    held = await triage.recall_hold(
        RecallHoldCommand(
            organization_id=organization_id,
            principal_id=principal_id,
            queue_entry_id=entries[0],
            condition_kind=RecallHoldKind.UNTIL_CUSTOMER_INITIATES,
            expected_revision=1,
            idempotency_key=f"hold-{uuid4().hex}",
        )
    )
    assert held.hold is not None

    with pytest.raises(RecallHoldConflict):
        await triage.release_recall_hold(
            release_command(organization_id, principal_id, entries[0], uuid4(), 2)
        )

    with pytest.raises(QueueEntryRevisionConflict):
        await triage.release_recall_hold(
            release_command(organization_id, principal_id, entries[0], held.hold.id, 1)
        )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_release_of_an_expired_time_hold_reports_holds_not_active(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    organization_id, principal_id, _queue_id, entries = create_world(admin_conn, 1)
    triage = PostgresQueueTriageCommands(app_session_factory)
    soon = datetime.now(tz=UTC) + timedelta(seconds=2)
    held = await triage.recall_hold(
        RecallHoldCommand(
            organization_id=organization_id,
            principal_id=principal_id,
            queue_entry_id=entries[0],
            condition_kind=RecallHoldKind.UNTIL_TIME,
            until_at=soon,
            expected_revision=1,
            idempotency_key=f"hold-{uuid4().hex}",
        )
    )
    assert held.hold is not None
    await asyncio.sleep(2.5)
    with pytest.raises(QueueHoldNotActive):
        await triage.release_recall_hold(
            release_command(organization_id, principal_id, entries[0], held.hold.id, 2)
        )
    # The failed release rolls back atomically: the expired hold stays unreleased
    # until the next successful queue command materializes the expiry.
    row = admin_conn.execute(
        """
        SELECT release_kind FROM request_engine.queue_entry_recall_holds
         WHERE organization_id = %s AND queue_entry_id = %s
        """,
        (organization_id, entries[0]),
    ).fetchone()
    assert row == (None,)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_release_after_the_entry_was_called_fails_closed(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    organization_id, principal_id, _queue_id, entries = create_world(admin_conn, 1)
    triage = PostgresQueueTriageCommands(app_session_factory)
    held = await triage.recall_hold(
        RecallHoldCommand(
            organization_id=organization_id,
            principal_id=principal_id,
            queue_entry_id=entries[0],
            condition_kind=RecallHoldKind.UNTIL_CUSTOMER_INITIATES,
            expected_revision=1,
            idempotency_key=f"hold-{uuid4().hex}",
        )
    )
    assert held.hold is not None
    selected = await triage.operator_select(
        OperatorSelectCommand(
            organization_id=organization_id,
            principal_id=principal_id,
            queue_entry_id=entries[0],
            reason=OperatorSelectReason.URGENT,
            expected_revision=2,
            idempotency_key=f"select-{uuid4().hex}",
        )
    )
    assert selected.status == "called"
    with pytest.raises(QueueEntryNotWaiting):
        await triage.release_recall_hold(
            release_command(organization_id, principal_id, entries[0], held.hold.id, 3)
        )
