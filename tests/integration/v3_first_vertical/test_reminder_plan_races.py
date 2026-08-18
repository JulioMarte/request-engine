# pyright: reportPrivateUsage=false

import asyncio
import json
from datetime import UTC, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection

from request_engine.modules.communications.adapters.db.reminder_commands import (
    REMINDER_ACTION_TYPE,
    PostgresReminderCommands,
)
from request_engine.modules.communications.adapters.db.reminder_occurrences import (
    PostgresReminderOccurrenceCommands,
)
from request_engine.modules.communications.application.commands.cancel_reminder_plan import (
    CancelReminderPlanCommand,
    cancel_reminder_plan,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.scheduling.postgres import (
    PostgresScheduledActionWorker,
    ScheduledActionLease,
)

from .test_communications_reminders import _create_fixture, _database_now, _uuid_row

PgConnection = Connection[Any]


def _seed_due_occurrence(
    admin_conn: PgConnection,
    *,
    organization_id: UUID,
    party_id: UUID,
) -> tuple[UUID, UUID]:
    plan_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.reminder_plans (
            organization_id,
            subject_party_id,
            purpose,
            timezone,
            schedule_spec,
            channel_policy,
            template_key,
            template_version
        ) VALUES (%s, %s, 'medication_reminder', 'UTC', %s::jsonb, %s::jsonb, %s, 1)
        RETURNING id
        """,
        (
            organization_id,
            party_id,
            json.dumps(
                {
                    "type": "daily_times",
                    "times": ["00:00:00"],
                    "max_lateness_minutes": 60,
                }
            ),
            json.dumps({"channels": ["whatsapp"], "provider_key": "n8n"}),
            "medication-reminder",
        ),
    )
    occurrence_at = _database_now(admin_conn).astimezone(UTC).replace(microsecond=0) - timedelta(
        minutes=5
    )
    action_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.scheduled_actions (
            organization_id,
            owner_module,
            action_type,
            action_version,
            subject_kind,
            subject_id,
            payload,
            dedupe_key,
            execute_at,
            next_attempt_at
        ) VALUES (
            %s, 'communications', %s, 1, 'ReminderPlan', %s,
            %s::jsonb, %s, %s, %s
        )
        RETURNING id
        """,
        (
            organization_id,
            REMINDER_ACTION_TYPE,
            plan_id,
            json.dumps(
                {
                    "reminder_plan_id": str(plan_id),
                    "plan_revision": 1,
                    "occurrence_at": occurrence_at.isoformat(),
                }
            ),
            f"r22-reminder:{plan_id}:r1:{occurrence_at.isoformat()}:{uuid4().hex}",
            occurrence_at,
            occurrence_at,
        ),
    )
    return plan_id, action_id


def _ungranted_lock_waiters(admin_conn: PgConnection) -> int:
    row = admin_conn.execute(
        """
        SELECT count(DISTINCT pid)
        FROM pg_locks
        WHERE NOT granted
          AND pid IS NOT NULL
          AND pid <> pg_backend_pid()
        """
    ).fetchone()
    assert row is not None
    return int(row[0])


async def _wait_for_new_lock_waiters(
    admin_conn: PgConnection,
    *,
    baseline: int,
    expected_new: int,
) -> None:
    deadline = asyncio.get_running_loop().time() + 5
    while asyncio.get_running_loop().time() < deadline:
        if _ungranted_lock_waiters(admin_conn) >= baseline + expected_new:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(
        f"expected at least {expected_new} new PostgreSQL lock waiters above baseline {baseline}"
    )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_r22_cancel_reminder_plan_vs_leased_occurrence_has_one_serialized_plan_outcome(
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

    cancellation = PostgresReminderCommands(app_session_factory)
    materializer = PostgresReminderOccurrenceCommands(app_session_factory)
    cancel_command = CancelReminderPlanCommand(
        organization_id=fixture.organization_id,
        principal_id=fixture.principal_id,
        reminder_plan_id=plan_id,
        expected_revision=1,
        reason="R22 concurrent cancellation",
        idempotency_key=f"r22-cancel-{uuid4().hex}",
    )

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
        cancel_task = asyncio.create_task(cancel_reminder_plan(cancellation, cancel_command))
        materialize_task = asyncio.create_task(materializer.materialize(lease))
        await _wait_for_new_lock_waiters(
            admin_conn,
            baseline=baseline_waiters,
            expected_new=2,
        )
        assert not cancel_task.done()
        assert not materialize_task.done()

    cancelled, materialized = await asyncio.gather(cancel_task, materialize_task)
    assert cancelled.status.value == "cancelled"
    assert cancelled.revision == 2

    plan_state = admin_conn.execute(
        """
        SELECT status, revision
        FROM request_engine.reminder_plans
        WHERE organization_id = %s AND id = %s
        """,
        (fixture.organization_id, plan_id),
    ).fetchone()
    assert plan_state == ("cancelled", 2)

    future_plan_actions = admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.scheduled_actions
        WHERE organization_id = %s
          AND owner_module = 'communications'
          AND action_type = %s
          AND subject_kind = 'ReminderPlan'
          AND subject_id = %s
          AND id <> %s
          AND status = 'pending'
        """,
        (fixture.organization_id, REMINDER_ACTION_TYPE, plan_id, action_id),
    ).fetchone()
    assert future_plan_actions == (0,)

    task_count_row = admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.communication_tasks
        WHERE organization_id = %s
          AND source_kind = 'ReminderPlan'
          AND source_id = %s
        """,
        (fixture.organization_id, plan_id),
    ).fetchone()
    assert task_count_row is not None
    task_count = cast(int, task_count_row[0])
    if materialized.skipped_reason == "plan_revision_stale":
        assert materialized.communication_task_id is None
        assert materialized.next_occurrence_at is None
        assert task_count == 0
    else:
        assert materialized.skipped_reason is None
        assert materialized.communication_task_id is not None
        assert task_count == 1
        task_state = admin_conn.execute(
            """
            SELECT status
            FROM request_engine.communication_tasks
            WHERE organization_id = %s
              AND id = %s
            """,
            (fixture.organization_id, materialized.communication_task_id),
        ).fetchone()
        assert task_state == ("cancelled",)
        dispatch = admin_conn.execute(
            """
            SELECT status
            FROM request_engine.scheduled_actions
            WHERE organization_id = %s
              AND action_type = 'dispatch_task'
              AND subject_kind = 'CommunicationTask'
              AND subject_id = %s
            """,
            (fixture.organization_id, materialized.communication_task_id),
        ).fetchone()
        assert dispatch == ("cancelled",)

    assert await worker.complete(lease) is True
    final_action = admin_conn.execute(
        "SELECT status FROM request_engine.scheduled_actions WHERE id = %s",
        (action_id,),
    ).fetchone()
    assert final_action == ("completed",)
