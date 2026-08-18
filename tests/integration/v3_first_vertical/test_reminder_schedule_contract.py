from datetime import time
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection, Error

from request_engine.modules.communications.adapters.db.reminder_commands import (
    REMINDER_SCHEDULE_TYPE,
    REMINDER_SCHEDULE_VERSION,
    PostgresReminderCommands,
    parse_daily_schedule,
)
from request_engine.modules.communications.application.commands.create_reminder_plan import (
    CreateReminderPlanCommand,
    create_reminder_plan,
)
from request_engine.platform.db.session import SessionFactory

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
        (f"i48-{suffix}", f"I48 {suffix}"),
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


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_i48_create_plan_persists_explicit_schedule_document_version(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
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
            idempotency_key=f"i48-create-{uuid4().hex}",
        ),
    )

    row = admin_conn.execute(
        """
        SELECT timezone,
               schedule_spec ->> 'type',
               schedule_spec -> 'version',
               schedule_spec -> 'times',
               revision
        FROM request_engine.reminder_plans
        WHERE organization_id = %s AND id = %s
        """,
        (organization_id, plan.id),
    ).fetchone()
    assert row == (
        "America/Santo_Domingo",
        REMINDER_SCHEDULE_TYPE,
        REMINDER_SCHEDULE_VERSION,
        ["08:00:00", "20:00:00"],
        1,
    )


@pytest.mark.integration
@pytest.mark.postgres
def test_i48_database_rejects_missing_or_unknown_schedule_document_version(
    admin_conn: PgConnection,
) -> None:
    organization_id, _principal_id, party_id = _fixture(admin_conn)

    for schedule_spec in (
        '{"type":"daily_times","times":["08:00:00"],"max_lateness_minutes":60}',
        '{"type":"daily_times","version":2,"times":["08:00:00"],"max_lateness_minutes":60}',
    ):
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
                    %s::jsonb, '{}'::jsonb, 'medication-reminder', 1
                )
                """,
                (organization_id, party_id, schedule_spec),
            )
        assert invalid_schedule.value.sqlstate == "23514"


@pytest.mark.integration
def test_i48_application_parser_fails_closed_on_unknown_schedule_document_version() -> None:
    valid: dict[str, object] = {
        "type": REMINDER_SCHEDULE_TYPE,
        "version": REMINDER_SCHEDULE_VERSION,
        "times": ["08:00:00"],
        "max_lateness_minutes": 60,
    }
    parsed = parse_daily_schedule(valid)
    assert parsed.times == (time(8, 0),)

    for invalid_version in (None, 0, 2, True, "1"):
        invalid: dict[str, object] = {**valid, "version": invalid_version}
        with pytest.raises(ValueError, match="unsupported reminder schedule version"):
            parse_daily_schedule(invalid)
