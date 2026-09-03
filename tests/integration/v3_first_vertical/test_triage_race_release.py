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
from request_engine.modules.queue.application.triage_errors import QueueHoldNotActive
from request_engine.modules.queue.contracts.service_queue import QueueEntry
from request_engine.modules.queue.contracts.triage import (
    OperatorSelectReason,
    QueueTriageResult,
    RecallHoldKind,
)
from request_engine.platform.db.session import SessionFactory

from .triage_race_support import race_behind_queue_lock
from .triage_scenario import PgConnection, create_world


def _service_queue_commands(session_factory: SessionFactory) -> PostgresServiceQueueCommands:
    return PostgresServiceQueueCommands(session_factory)


def _release(
    triage: PostgresQueueTriageCommands,
    organization_id: UUID,
    principal_id: UUID,
    entry_id: UUID,
    hold_id: UUID,
    expected_revision: int,
):
    return triage.release_recall_hold(
        ReleaseRecallHoldCommand(
            organization_id=organization_id,
            principal_id=principal_id,
            queue_entry_id=entry_id,
            hold_id=hold_id,
            expected_revision=expected_revision,
            idempotency_key=f"release-{uuid4().hex}",
        )
    )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_release_vs_release_has_exactly_one_winner(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    organization_id, principal_id, queue_id, entries = create_world(admin_conn, 1)
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

    first, second = await race_behind_queue_lock(
        admin_conn,
        organization_id,
        queue_id,
        _release(triage, organization_id, principal_id, entries[0], held.hold.id, 2),
        _release(triage, organization_id, principal_id, entries[0], held.hold.id, 2),
    )
    state = admin_conn.execute(
        """
        SELECT status, revision FROM request_engine.queue_entries
         WHERE organization_id = %s AND id = %s
        """,
        (organization_id, entries[0]),
    ).fetchone()
    released = admin_conn.execute(
        """
        SELECT release_kind FROM request_engine.queue_entry_recall_holds
         WHERE organization_id = %s AND queue_entry_id = %s AND released_at IS NOT NULL
        """,
        (organization_id, entries[0]),
    ).fetchall()
    assert state is not None
    assert state[0] == "waiting"
    assert len(released) == 1
    assert released[0] == ("operator_release",)
    winners = [r for r in (first, second) if isinstance(r, QueueTriageResult)]
    assert len(winners) == 1
    assert winners[0].revision == state[1]


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_release_vs_operator_select_serializes_without_losing_the_call(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    organization_id, principal_id, queue_id, entries = create_world(admin_conn, 1)
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

    release_result, select_result = await race_behind_queue_lock(
        admin_conn,
        organization_id,
        queue_id,
        _release(triage, organization_id, principal_id, entries[0], held.hold.id, 2),
        triage.operator_select(
            OperatorSelectCommand(
                organization_id=organization_id,
                principal_id=principal_id,
                queue_entry_id=entries[0],
                reason=OperatorSelectReason.URGENT,
                expected_revision=2,
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
    released = admin_conn.execute(
        """
        SELECT release_kind FROM request_engine.queue_entry_recall_holds
         WHERE organization_id = %s AND queue_entry_id = %s AND released_at IS NOT NULL
        """,
        (organization_id, entries[0]),
    ).fetchall()
    assert state is not None
    if state[0] == "called":
        # The selection won: the entry is called, its hold exited as operator_select
        # and the release attempt found nothing active.
        assert isinstance(select_result, QueueTriageResult)
        assert isinstance(release_result, QueueHoldNotActive)
        assert released == [("operator_select",)]
        assert state == ("called", 3)
    else:
        # The release won: the entry is waiting again and the selection conflicted.
        assert state == ("waiting", 3)
        assert isinstance(release_result, QueueTriageResult)
        assert select_result is not None and not isinstance(select_result, QueueTriageResult)
        assert released == [("operator_release",)]


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_release_vs_call_next_never_loses_a_hold_or_double_calls(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    organization_id, principal_id, queue_id, entries = create_world(admin_conn, 1)
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

    release_result, call_result = await race_behind_queue_lock(
        admin_conn,
        organization_id,
        queue_id,
        _release(triage, organization_id, principal_id, entries[0], held.hold.id, 2),
        call_next(
            _service_queue_commands(app_session_factory),
            CallNextCommand(
                organization_id=organization_id,
                principal_id=principal_id,
                queue_id=queue_id,
                idempotency_key=f"call-{uuid4().hex}",
            ),
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
    calls = admin_conn.execute(
        """
        SELECT count(*) FROM request_engine.outbox_messages
         WHERE organization_id = %s AND aggregate_id = %s
           AND event_type = 'queue.entry_called.v1'
        """,
        (organization_id, entries[0]),
    ).fetchone()
    assert state is not None
    if state[0] == "called":
        # The release ran first and freed the entry; call_next then called it.
        assert isinstance(call_result, QueueEntry)
        assert isinstance(release_result, QueueTriageResult)
        assert calls == (1,)
        assert active_holds == (0,)
        assert state == ("called", 4)
    else:
        # call_next ran first, found only a held entry, and called nobody;
        # the release then returned the entry to the plain FIFO.
        assert state == ("waiting", 3)
        assert isinstance(release_result, QueueTriageResult)
        assert call_result is None
        assert calls == (0,)
        assert active_holds == (0,)
