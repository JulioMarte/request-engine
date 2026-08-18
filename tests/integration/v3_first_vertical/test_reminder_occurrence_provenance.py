import json
from datetime import UTC, datetime, time, timedelta
from typing import Any, LiteralString, cast
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
from request_engine.modules.communications.application.commands.create_reminder_plan import (
    CreateReminderPlanCommand,
    create_reminder_plan,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.scheduling.postgres import PostgresScheduledActionWorker
from request_engine.platform.worker.runtime import PermanentWorkError

PgConnection = Connection[Any]


def _uuid_row(
    conn: PgConnection,
    sql: LiteralString,
    params: tuple[object, ...] = (),
) -> UUID:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


async def _create_plan(
    conn: PgConnection,
    session_factory: SessionFactory,
) -> tuple[UUID, UUID]:
    suffix = uuid4().hex
    organization_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (f"i49-provenance-{suffix}", f"I49 provenance {suffix}"),
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
    plan = await create_reminder_plan(
        PostgresReminderCommands(session_factory),
        CreateReminderPlanCommand(
            organization_id=organization_id,
            principal_id=principal_id,
            subject_party_id=party_id,
            purpose="medication_reminder",
            timezone="UTC",
            daily_times=(time(8, 0),),
            max_lateness_minutes=60,
            channel_policy={"channels": ["whatsapp"], "provider_key": "test"},
            template_key="medication-reminder",
            template_version=1,
            idempotency_key=f"i49-plan-{uuid4().hex}",
        ),
    )
    return organization_id, plan.id


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_i49_missing_plan_revision_provenance_is_rejected_before_materialization(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
    worker_session_factory: SessionFactory,
) -> None:
    organization_id, plan_id = await _create_plan(admin_conn, session_factory)
    occurrence_at = datetime.now(UTC) - timedelta(minutes=1)
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
                    "occurrence_at": occurrence_at.isoformat(),
                }
            ),
            f"i49-missing-provenance:{plan_id}:{uuid4().hex}",
            occurrence_at,
            occurrence_at,
        ),
    )

    worker = PostgresScheduledActionWorker(worker_session_factory)
    lease = next(item for item in await worker.claim(limit=500) if item.id == action_id)
    with pytest.raises(PermanentWorkError, match="reminder_scheduled_action_payload_invalid"):
        await PostgresReminderOccurrenceCommands(session_factory).materialize(lease)

    assert admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.communication_tasks
        WHERE organization_id = %s
          AND source_kind = 'ReminderPlan'
          AND source_id = %s
        """,
        (organization_id, plan_id),
    ).fetchone() == (0,)
