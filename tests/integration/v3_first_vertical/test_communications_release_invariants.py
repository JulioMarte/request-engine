import json
from datetime import UTC, datetime, time, timedelta
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection, Error

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
from request_engine.modules.communications.application.commands.create_reminder_plan import (
    CreateReminderPlanCommand,
    create_reminder_plan,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.scheduling.postgres import PostgresScheduledActionWorker

PgConnection = Connection[Any]


def _uuid_row(
    conn: PgConnection,
    sql: LiteralString,
    params: tuple[object, ...] = (),
) -> UUID:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _fixture(conn: PgConnection) -> tuple[UUID, UUID, UUID]:
    suffix = uuid4().hex
    organization_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (f"communications-release-{suffix}", f"Communications Release {suffix}"),
    )
    principal_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.principals (
            organization_id, principal_kind, external_subject
        ) VALUES (%s, 'agent', %s)
        RETURNING id
        """,
        (organization_id, f"agent-{suffix}"),
    )
    party_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.parties (organization_id, party_kind, display_name)
        VALUES (%s, 'person', %s)
        RETURNING id
        """,
        (organization_id, f"Subject {suffix}"),
    )
    conn.execute(
        """
        INSERT INTO request_engine.representations (
            organization_id,
            principal_id,
            represented_party_id,
            scope_key,
            authority_kind
        ) VALUES (%s, %s, %s, 'reminders.manage', 'self')
        """,
        (organization_id, principal_id, party_id),
    )
    return organization_id, principal_id, party_id


async def _create_plan(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> tuple[UUID, UUID, UUID]:
    organization_id, principal_id, party_id = _fixture(admin_conn)
    plan = await create_reminder_plan(
        PostgresReminderCommands(session_factory),
        CreateReminderPlanCommand(
            organization_id=organization_id,
            principal_id=principal_id,
            subject_party_id=party_id,
            purpose="medication_reminder",
            timezone="America/Santo_Domingo",
            daily_times=(time(8, 0), time(20, 0)),
            max_lateness_minutes=60,
            channel_policy={"channels": ["whatsapp"], "provider_key": "test"},
            template_key="medication-reminder",
            template_version=1,
            idempotency_key=f"create-reminder-{uuid4().hex}",
        ),
    )
    return organization_id, principal_id, plan.id


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_i48_reminder_schedule_type_timezone_and_version_are_explicit(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    organization_id, _principal_id, plan_id = await _create_plan(admin_conn, session_factory)

    row = admin_conn.execute(
        """
        SELECT timezone,
               schedule_spec ->> 'type',
               schedule_spec -> 'times',
               revision
        FROM request_engine.reminder_plans
        WHERE organization_id = %s AND id = %s
        """,
        (organization_id, plan_id),
    ).fetchone()
    assert row is not None
    assert row[0] == "America/Santo_Domingo"
    assert row[1] == "daily_times"
    assert row[2] == ["08:00:00", "20:00:00"]
    assert row[3] == 1

    party_id = cast(
        UUID,
        admin_conn.execute(
            "SELECT subject_party_id FROM request_engine.reminder_plans WHERE id = %s",
            (plan_id,),
        ).fetchone()[0],
    )
    with pytest.raises(Error) as invalid_schedule:
        admin_conn.execute(
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
            ) VALUES (
                %s, %s, 'medication_reminder', 'UTC',
                '{"type":"cron","expression":"* * * * *"}'::jsonb,
                '{}'::jsonb,
                'invalid-cron', 1
            )
            """,
            (organization_id, party_id),
        )
    assert invalid_schedule.value.sqlstate == "23514"


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_i49_reminder_occurrence_is_bound_to_plan_revision(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
    worker_session_factory: SessionFactory,
) -> None:
    organization_id, _principal_id, plan_id = await _create_plan(admin_conn, session_factory)

    scheduled = admin_conn.execute(
        """
        SELECT payload ->> 'plan_revision', dedupe_key
        FROM request_engine.scheduled_actions
        WHERE organization_id = %s
          AND owner_module = 'communications'
          AND action_type = %s
          AND subject_kind = 'ReminderPlan'
          AND subject_id = %s
        ORDER BY created_at, id
        LIMIT 1
        """,
        (organization_id, REMINDER_ACTION_TYPE, plan_id),
    ).fetchone()
    assert scheduled is not None
    assert scheduled[0] == "1"
    assert f":{plan_id}:r1:" in cast(str, scheduled[1])

    occurrence_at = datetime.now(UTC) - timedelta(minutes=1)
    stale_action_id = _uuid_row(
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
                    "plan_revision": 2,
                    "occurrence_at": occurrence_at.isoformat(),
                }
            ),
            f"i49-stale:{plan_id}:{uuid4().hex}",
            occurrence_at,
            occurrence_at,
        ),
    )

    worker = PostgresScheduledActionWorker(worker_session_factory)
    lease = next(item for item in await worker.claim(limit=500) if item.id == stale_action_id)
    result = await PostgresReminderOccurrenceCommands(session_factory).materialize(lease)
    assert result.communication_task_id is None
    assert result.skipped_reason == "plan_revision_stale"
    assert await worker.complete(lease) is True

    task_count = admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.communication_tasks
        WHERE organization_id = %s
          AND source_kind = 'ReminderPlan'
          AND source_id = %s
        """,
        (organization_id, plan_id),
    ).fetchone()
    assert task_count == (0,)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_i50_cancel_plan_cancels_pending_derived_work_and_preserves_delivery_history(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
    worker_session_factory: SessionFactory,
) -> None:
    organization_id, principal_id, plan_id = await _create_plan(admin_conn, session_factory)
    occurrence_at = datetime.now(UTC) - timedelta(minutes=1)
    occurrence_action_id = _uuid_row(
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
            f"i50-current:{plan_id}:{uuid4().hex}",
            occurrence_at,
            occurrence_at,
        ),
    )

    worker = PostgresScheduledActionWorker(worker_session_factory)
    occurrence_lease = next(
        item for item in await worker.claim(limit=500) if item.id == occurrence_action_id
    )
    materialized = await PostgresReminderOccurrenceCommands(session_factory).materialize(
        occurrence_lease
    )
    assert materialized.communication_task_id is not None
    pending_task_id = materialized.communication_task_id
    assert await worker.complete(occurrence_lease) is True

    pending_before = admin_conn.execute(
        """
        SELECT ct.status, sa.status
        FROM request_engine.communication_tasks ct
        JOIN request_engine.scheduled_actions sa
          ON sa.organization_id = ct.organization_id
         AND sa.subject_kind = 'CommunicationTask'
         AND sa.subject_id = ct.id
         AND sa.action_type = 'dispatch_task'
        WHERE ct.organization_id = %s AND ct.id = %s
        """,
        (organization_id, pending_task_id),
    ).fetchone()
    assert pending_before == ("pending", "pending")

    subject_party_id = cast(
        UUID,
        admin_conn.execute(
            "SELECT subject_party_id FROM request_engine.reminder_plans WHERE id = %s",
            (plan_id,),
        ).fetchone()[0],
    )
    history_task_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.communication_tasks (
            organization_id,
            recipient_party_id,
            purpose,
            source_kind,
            source_id,
            channel_policy,
            template_key,
            template_version,
            render_context,
            dedupe_key,
            status
        ) VALUES (
            %s, %s, 'medication_reminder', 'ReminderPlan', %s,
            '{}'::jsonb, 'medication-reminder', 1, '{}'::jsonb, %s, 'completed'
        )
        RETURNING id
        """,
        (organization_id, subject_party_id, plan_id, f"history:{uuid4().hex}"),
    )
    history_delivery_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.communication_deliveries (
            organization_id,
            communication_task_id,
            attempt_no,
            channel,
            provider_key,
            provider_idempotency_key,
            provider_message_id,
            status
        ) VALUES (%s, %s, 1, 'whatsapp', 'history-provider', %s, %s, 'delivered')
        RETURNING id
        """,
        (
            organization_id,
            history_task_id,
            f"history-send:{uuid4().hex}",
            f"history-message:{uuid4().hex}",
        ),
    )

    cancelled = await cancel_reminder_plan(
        PostgresReminderCommands(session_factory),
        CancelReminderPlanCommand(
            organization_id=organization_id,
            principal_id=principal_id,
            reminder_plan_id=plan_id,
            expected_revision=1,
            reason="release invariant proof",
            idempotency_key=f"cancel-reminder-{uuid4().hex}",
        ),
    )
    assert cancelled.status.value == "cancelled"
    assert cancelled.revision == 2

    pending_after = admin_conn.execute(
        """
        SELECT ct.status, sa.status
        FROM request_engine.communication_tasks ct
        JOIN request_engine.scheduled_actions sa
          ON sa.organization_id = ct.organization_id
         AND sa.subject_kind = 'CommunicationTask'
         AND sa.subject_id = ct.id
         AND sa.action_type = 'dispatch_task'
        WHERE ct.organization_id = %s AND ct.id = %s
        """,
        (organization_id, pending_task_id),
    ).fetchone()
    assert pending_after == ("cancelled", "cancelled")

    history_after = admin_conn.execute(
        """
        SELECT ct.status, cd.status, cd.provider_message_id
        FROM request_engine.communication_tasks ct
        JOIN request_engine.communication_deliveries cd
          ON cd.organization_id = ct.organization_id
         AND cd.communication_task_id = ct.id
        WHERE ct.organization_id = %s
          AND ct.id = %s
          AND cd.id = %s
        """,
        (organization_id, history_task_id, history_delivery_id),
    ).fetchone()
    assert history_after is not None
    assert history_after[0] == "completed"
    assert history_after[1] == "delivered"
    assert cast(str, history_after[2]).startswith("history-message:")
