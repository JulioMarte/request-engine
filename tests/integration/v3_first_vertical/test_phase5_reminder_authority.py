from datetime import time
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection

from request_engine.modules.communications.adapters.db.reminder_commands import (
    PostgresReminderCommands,
)
from request_engine.modules.communications.application.commands.cancel_reminder_plan import (
    CancelReminderPlanCommand,
    cancel_reminder_plan,
)
from request_engine.modules.communications.application.commands.create_reminder_plan import (
    CreateReminderPlanCommand,
    create_reminder_plan,
)
from request_engine.modules.communications.application.errors import (
    ReminderPlanRevisionConflict,
    ReminderSubjectAuthorityRequired,
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


def _fixture(conn: PgConnection, *, with_authority: bool) -> tuple[UUID, UUID, UUID]:
    suffix = uuid4().hex
    organization_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (f"reminder-auth-{suffix}", f"Reminder Auth {suffix}"),
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
        INSERT INTO request_engine.party_contact_points (
            organization_id, party_id, channel, normalized_value, verified
        ) VALUES (%s, %s, 'whatsapp', %s, true)
        """,
        (organization_id, party_id, f"+1809{suffix[:7]}"),
    )
    if with_authority:
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


def _create_command(
    organization_id: UUID,
    principal_id: UUID,
    party_id: UUID,
    *,
    allow_subject_override: bool = False,
) -> CreateReminderPlanCommand:
    return CreateReminderPlanCommand(
        organization_id=organization_id,
        principal_id=principal_id,
        subject_party_id=party_id,
        purpose="medication_reminder",
        timezone="America/Santo_Domingo",
        daily_times=(time(8, 0),),
        channel_policy={"channels": ["whatsapp"]},
        template_key="medication-reminder",
        template_version=1,
        idempotency_key=f"create-{uuid4().hex}",
        allow_subject_override=allow_subject_override,
    )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_reminder_create_requires_current_party_authority(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    organization_id, principal_id, party_id = _fixture(admin_conn, with_authority=False)

    with pytest.raises(ReminderSubjectAuthorityRequired):
        await create_reminder_plan(
            PostgresReminderCommands(session_factory),
            _create_command(organization_id, principal_id, party_id),
        )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_reminder_cancel_checks_authority_before_revision_conflict(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    organization_id, principal_id, party_id = _fixture(admin_conn, with_authority=False)
    commands = PostgresReminderCommands(session_factory)
    plan = await create_reminder_plan(
        commands,
        _create_command(
            organization_id,
            principal_id,
            party_id,
            allow_subject_override=True,
        ),
    )

    with pytest.raises(ReminderSubjectAuthorityRequired):
        await cancel_reminder_plan(
            commands,
            CancelReminderPlanCommand(
                organization_id=organization_id,
                principal_id=principal_id,
                reminder_plan_id=plan.id,
                expected_revision=plan.revision + 99,
                idempotency_key=f"cancel-{uuid4().hex}",
            ),
        )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_authorized_reminder_cancel_rejects_stale_revision(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    organization_id, principal_id, party_id = _fixture(admin_conn, with_authority=True)
    commands = PostgresReminderCommands(session_factory)
    plan = await create_reminder_plan(
        commands,
        _create_command(organization_id, principal_id, party_id),
    )

    with pytest.raises(ReminderPlanRevisionConflict):
        await cancel_reminder_plan(
            commands,
            CancelReminderPlanCommand(
                organization_id=organization_id,
                principal_id=principal_id,
                reminder_plan_id=plan.id,
                expected_revision=plan.revision + 1,
                idempotency_key=f"cancel-{uuid4().hex}",
            ),
        )
