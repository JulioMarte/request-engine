# pyright: reportPrivateUsage=false

import asyncio

import pytest

from request_engine.modules.communications.adapters.db.reminder_occurrences import (
    PostgresReminderOccurrenceCommands,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.scheduling.postgres import (
    PostgresScheduledActionWorker,
    ScheduledActionLease,
)

from .test_communications_reminders import _create_fixture
from .test_reminder_plan_races import (
    PgConnection,
    _seed_due_occurrence,
    _ungranted_lock_waiters,
    _wait_for_new_lock_waiters,
)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_r21_duplicate_reminder_materialization_serializes_to_one_occurrence_graph(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
    worker_session_factory: SessionFactory,
) -> None:
    fixture = _create_fixture(admin_conn)
    plan_id, action_id = _seed_due_occurrence(
        admin_conn,
        organization_id=fixture.organization_id,
        party_id=fixture.party_id,
    )
    worker = PostgresScheduledActionWorker(worker_session_factory)
    lease = next(item for item in await worker.claim(limit=500) if item.id == action_id)
    assert isinstance(lease, ScheduledActionLease)

    materializer = PostgresReminderOccurrenceCommands(app_session_factory)

    with admin_conn.transaction():
        admin_conn.execute(
            """
            SELECT id
            FROM request_engine.reminder_plans
            WHERE organization_id = %s AND id = %s
            FOR UPDATE
            """,
            (fixture.organization_id, plan_id),
        ).fetchone()
        baseline_waiters = _ungranted_lock_waiters(admin_conn)
        first_task = asyncio.create_task(materializer.materialize(lease))
        second_task = asyncio.create_task(materializer.materialize(lease))
        await _wait_for_new_lock_waiters(
            admin_conn,
            baseline=baseline_waiters,
            expected_new=2,
        )
        assert not first_task.done()
        assert not second_task.done()

    first, second = await asyncio.gather(first_task, second_task)
    assert first.skipped_reason is None
    assert second.skipped_reason is None
    assert first.communication_task_id is not None
    assert second.communication_task_id == first.communication_task_id
    assert first.next_occurrence_at is not None
    assert second.next_occurrence_at == first.next_occurrence_at

    task_id = first.communication_task_id
    task_count = admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.communication_tasks
        WHERE organization_id = %s
          AND source_kind = 'ReminderPlan'
          AND source_id = %s
        """,
        (fixture.organization_id, plan_id),
    ).fetchone()
    assert task_count == (1,)

    dispatch_count = admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.scheduled_actions
        WHERE organization_id = %s
          AND action_type = 'dispatch_task'
          AND subject_kind = 'CommunicationTask'
          AND subject_id = %s
        """,
        (fixture.organization_id, task_id),
    ).fetchone()
    assert dispatch_count == (1,)

    next_occurrences = admin_conn.execute(
        """
        SELECT execute_at
        FROM request_engine.scheduled_actions
        WHERE organization_id = %s
          AND owner_module = 'communications'
          AND subject_kind = 'ReminderPlan'
          AND subject_id = %s
          AND id <> %s
          AND status = 'pending'
        ORDER BY execute_at, id
        """,
        (fixture.organization_id, plan_id, action_id),
    ).fetchall()
    assert next_occurrences == [(first.next_occurrence_at,)]

    outbox_count = admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.outbox_messages
        WHERE organization_id = %s
          AND event_type = 'communication.task_created.v1'
          AND aggregate_id = %s
        """,
        (fixture.organization_id, task_id),
    ).fetchone()
    assert outbox_count == (1,)

    assert await worker.complete(lease) is True
    assert await worker.complete(lease) is False
    final_action = admin_conn.execute(
        "SELECT status FROM request_engine.scheduled_actions WHERE id = %s",
        (action_id,),
    ).fetchone()
    assert final_action == ("completed",)
