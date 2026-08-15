import json
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection

from request_engine.modules.communications.adapters.db.communication_commands import (
    PostgresCommunicationCommands,
)
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
from request_engine.modules.communications.application.commands.create_communication_task import (
    CreateCommunicationTaskCommand,
    create_communication_task,
)
from request_engine.modules.communications.application.commands.create_reminder_plan import (
    CreateReminderPlanCommand,
    create_reminder_plan,
)
from request_engine.modules.communications.application.errors import CommunicationDedupeConflict
from request_engine.modules.communications.contracts.reminders import ReminderPlanStatus
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.scheduling.postgres import PostgresScheduledActionWorker

PgConnection = Connection[Any]


@dataclass(frozen=True, slots=True)
class CommunicationFixture:
    organization_id: UUID
    principal_id: UUID
    party_id: UUID
    contact_point_id: UUID


def _uuid_row(
    conn: PgConnection,
    sql: LiteralString,
    params: tuple[object, ...] = (),
) -> UUID:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _database_now(conn: PgConnection) -> datetime:
    row = conn.execute("SELECT clock_timestamp()").fetchone()
    assert row is not None
    return cast(datetime, row[0])


def _create_fixture(conn: PgConnection) -> CommunicationFixture:
    suffix = uuid4().hex
    organization_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (f"communications-{suffix}", f"Communications Practice {suffix}"),
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
        (organization_id, f"Patient {suffix}"),
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
    contact_point_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.party_contact_points (
            organization_id, party_id, channel, normalized_value, verified
        ) VALUES (%s, %s, 'whatsapp', %s, true)
        RETURNING id
        """,
        (organization_id, party_id, f"+1809{suffix[:7]}"),
    )
    return CommunicationFixture(
        organization_id=organization_id,
        principal_id=principal_id,
        party_id=party_id,
        contact_point_id=contact_point_id,
    )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_communication_task_is_idempotent_deduped_and_durably_scheduled(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = _create_fixture(admin_conn)
    commands = PostgresCommunicationCommands(session_factory)
    db_now = _database_now(admin_conn)
    not_before = db_now + timedelta(minutes=5)
    expires_at = db_now + timedelta(minutes=30)
    dedupe_key = f"appointment-confirmation:{uuid4().hex}"
    command = CreateCommunicationTaskCommand(
        organization_id=fixture.organization_id,
        principal_id=fixture.principal_id,
        recipient_party_id=fixture.party_id,
        contact_point_id=fixture.contact_point_id,
        purpose="appointment_confirmation",
        template_key="appointment-confirmation",
        template_version=1,
        channel_policy={"channels": ["whatsapp"], "provider_key": "n8n"},
        render_context={"reservation_id": str(uuid4())},
        dedupe_key=dedupe_key,
        not_before=not_before,
        expires_at=expires_at,
        idempotency_key=f"communication-{uuid4().hex}",
    )

    task = await create_communication_task(commands, command)
    replay = await create_communication_task(commands, command)
    assert replay == task

    same_intent = await create_communication_task(
        commands,
        CreateCommunicationTaskCommand(
            organization_id=command.organization_id,
            principal_id=command.principal_id,
            recipient_party_id=command.recipient_party_id,
            contact_point_id=command.contact_point_id,
            purpose=command.purpose,
            template_key=command.template_key,
            template_version=command.template_version,
            channel_policy=command.channel_policy,
            render_context=command.render_context,
            dedupe_key=command.dedupe_key,
            not_before=command.not_before,
            expires_at=command.expires_at,
            idempotency_key=f"communication-{uuid4().hex}",
        ),
    )
    assert same_intent == task

    with pytest.raises(CommunicationDedupeConflict):
        await create_communication_task(
            commands,
            CreateCommunicationTaskCommand(
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                recipient_party_id=command.recipient_party_id,
                contact_point_id=command.contact_point_id,
                purpose="reservation_changed",
                template_key=command.template_key,
                template_version=command.template_version,
                channel_policy=command.channel_policy,
                render_context=command.render_context,
                dedupe_key=command.dedupe_key,
                not_before=command.not_before,
                expires_at=command.expires_at,
                idempotency_key=f"communication-{uuid4().hex}",
            ),
        )

    scheduled = admin_conn.execute(
        """
        SELECT action_type, execute_at, count(*)
        FROM request_engine.scheduled_actions
        WHERE organization_id = %s
          AND subject_kind = 'CommunicationTask'
          AND subject_id = %s
        GROUP BY action_type, execute_at
        """,
        (fixture.organization_id, task.id),
    ).fetchone()
    assert scheduled == ("dispatch_task", not_before, 1)

    outbox_count = admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.outbox_messages
        WHERE organization_id = %s
          AND event_type = 'communication.task_created.v1'
          AND aggregate_id = %s
        """,
        (fixture.organization_id, task.id),
    ).fetchone()
    assert outbox_count == (1,)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_reminder_plan_creation_and_cancellation_own_future_schedule(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = _create_fixture(admin_conn)
    commands = PostgresReminderCommands(session_factory)
    create_command = CreateReminderPlanCommand(
        organization_id=fixture.organization_id,
        principal_id=fixture.principal_id,
        subject_party_id=fixture.party_id,
        purpose="medication_reminder",
        timezone="America/Santo_Domingo",
        daily_times=(time(8, 0), time(20, 0)),
        max_lateness_minutes=45,
        channel_policy={"channels": ["whatsapp"], "provider_key": "n8n"},
        template_key="medication-reminder",
        template_version=1,
        idempotency_key=f"reminder-plan-{uuid4().hex}",
    )

    plan = await create_reminder_plan(commands, create_command)
    replay = await create_reminder_plan(commands, create_command)
    assert replay == plan
    assert plan.schedule.times == (time(8, 0), time(20, 0))
    assert plan.schedule.max_lateness_minutes == 45
    assert plan.status is ReminderPlanStatus.ACTIVE

    pending_action = admin_conn.execute(
        """
        SELECT status, execute_at
        FROM request_engine.scheduled_actions
        WHERE organization_id = %s
          AND owner_module = 'communications'
          AND action_type = %s
          AND subject_kind = 'ReminderPlan'
          AND subject_id = %s
        """,
        (fixture.organization_id, REMINDER_ACTION_TYPE, plan.id),
    ).fetchone()
    assert pending_action is not None
    assert pending_action[0] == "pending"
    assert cast(datetime, pending_action[1]) > _database_now(admin_conn)

    cancelled = await cancel_reminder_plan(
        commands,
        CancelReminderPlanCommand(
            organization_id=fixture.organization_id,
            principal_id=fixture.principal_id,
            reminder_plan_id=plan.id,
            expected_revision=plan.revision,
            reason="plan no longer needed",
            idempotency_key=f"cancel-reminder-{uuid4().hex}",
        ),
    )
    assert cancelled.status is ReminderPlanStatus.CANCELLED
    assert cancelled.revision == plan.revision + 1

    action_status = admin_conn.execute(
        """
        SELECT status
        FROM request_engine.scheduled_actions
        WHERE organization_id = %s
          AND owner_module = 'communications'
          AND action_type = %s
          AND subject_id = %s
        """,
        (fixture.organization_id, REMINDER_ACTION_TYPE, plan.id),
    ).fetchone()
    assert action_status == ("cancelled",)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_reminder_occurrence_materialization_is_crash_replay_safe(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
    worker_session_factory: SessionFactory,
) -> None:
    fixture = _create_fixture(admin_conn)
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
            fixture.organization_id,
            fixture.party_id,
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
            fixture.organization_id,
            REMINDER_ACTION_TYPE,
            plan_id,
            json.dumps(
                {
                    "reminder_plan_id": str(plan_id),
                    "occurrence_at": occurrence_at.isoformat(),
                }
            ),
            f"test-reminder:{plan_id}:{occurrence_at.isoformat()}",
            occurrence_at,
            occurrence_at,
        ),
    )

    worker = PostgresScheduledActionWorker(worker_session_factory)
    leases = await worker.claim(limit=500)
    lease = next(item for item in leases if item.id == action_id)
    materializer = PostgresReminderOccurrenceCommands(worker_session_factory)

    first = await materializer.materialize(lease)
    second = await materializer.materialize(lease)
    assert first.communication_task_id is not None
    assert second.communication_task_id == first.communication_task_id
    assert second.next_occurrence_at == first.next_occurrence_at
    assert first.next_occurrence_at is not None
    assert first.next_occurrence_at > _database_now(admin_conn)

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
        (fixture.organization_id, first.communication_task_id),
    ).fetchone()
    assert dispatch_count == (1,)

    next_count = admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.scheduled_actions
        WHERE organization_id = %s
          AND action_type = %s
          AND subject_kind = 'ReminderPlan'
          AND subject_id = %s
          AND execute_at > %s
        """,
        (fixture.organization_id, REMINDER_ACTION_TYPE, plan_id, occurrence_at),
    ).fetchone()
    assert next_count == (1,)

    assert await worker.complete(lease) is True
    assert await worker.complete(lease) is False


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_stale_reminder_occurrence_is_skipped_without_catchup_send(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
    worker_session_factory: SessionFactory,
) -> None:
    fixture = _create_fixture(admin_conn)
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
        ) VALUES (%s, %s, 'medication_reminder', 'UTC', %s::jsonb, '{}'::jsonb, %s, 1)
        RETURNING id
        """,
        (
            fixture.organization_id,
            fixture.party_id,
            json.dumps(
                {
                    "type": "daily_times",
                    "times": ["00:00:00"],
                    "max_lateness_minutes": 1,
                }
            ),
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
            fixture.organization_id,
            REMINDER_ACTION_TYPE,
            plan_id,
            json.dumps(
                {
                    "reminder_plan_id": str(plan_id),
                    "occurrence_at": occurrence_at.isoformat(),
                }
            ),
            f"test-stale-reminder:{plan_id}:{occurrence_at.isoformat()}",
            occurrence_at,
            occurrence_at,
        ),
    )

    worker = PostgresScheduledActionWorker(worker_session_factory)
    lease = next(item for item in await worker.claim(limit=500) if item.id == action_id)
    result = await PostgresReminderOccurrenceCommands(worker_session_factory).materialize(lease)

    assert result.communication_task_id is None
    assert result.skipped_reason == "occurrence_too_late"
    assert result.next_occurrence_at is not None
    assert result.next_occurrence_at > _database_now(admin_conn)

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
    assert task_count == (0,)
