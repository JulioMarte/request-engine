# pyright: reportPrivateUsage=false

import asyncio
from typing import Any, cast
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
    create_reminder_plan,
)
from request_engine.modules.communications.application.errors import (
    ReminderSubjectAuthorityRequired,
)
from request_engine.modules.communications.contracts.reminders import ReminderPlanStatus
from request_engine.platform.db.session import SessionFactory

from ._authority_race_support import (
    assert_revoke_blocked,
    begin_revoke,
    connect,
    lock_audit_barrier,
    revoke_and_commit,
    wait_until_audit_blocked,
    wait_until_authority_blocked,
)
from .test_phase5_reminder_authority import _create_command, _fixture

PgConnection = Connection[Any]


async def _active_plan(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
):
    organization_id, principal_id, party_id = _fixture(admin_conn, with_authority=True)
    commands = PostgresReminderCommands(app_session_factory)
    plan = await create_reminder_plan(
        commands,
        _create_command(organization_id, principal_id, party_id),
    )
    row = admin_conn.execute(
        """
        SELECT id
        FROM request_engine.representations
        WHERE organization_id = %s
          AND principal_id = %s
          AND represented_party_id = %s
          AND scope_key = 'reminders.manage'
          AND status = 'active'
        """,
        (organization_id, principal_id, party_id),
    ).fetchone()
    assert row is not None
    return organization_id, principal_id, commands, plan, cast(UUID, row[0])


def _cancel_command(*, organization_id, principal_id, plan, key: str) -> CancelReminderPlanCommand:
    return CancelReminderPlanCommand(
        organization_id=organization_id,
        principal_id=principal_id,
        reminder_plan_id=plan.id,
        expected_revision=plan.revision,
        reason="party-authority race",
        idempotency_key=key,
    )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_reminders_manage_command_first_holds_authority_until_commit(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    organization_id, principal_id, commands, plan, representation_id = await _active_plan(
        admin_conn,
        app_session_factory,
    )
    blocker = connect()
    revoker = connect()
    try:
        lock_audit_barrier(blocker)
        task = asyncio.create_task(
            cancel_reminder_plan(
                commands,
                _cancel_command(
                    organization_id=organization_id,
                    principal_id=principal_id,
                    plan=plan,
                    key=f"reminder-manage-command-first-{uuid4().hex}",
                ),
            )
        )
        await wait_until_audit_blocked(admin_conn)
        assert_revoke_blocked(
            revoker,
            organization_id=organization_id,
            representation_id=representation_id,
        )
        blocker.commit()
        cancelled = await asyncio.wait_for(task, timeout=5)
        assert cancelled.status is ReminderPlanStatus.CANCELLED
        assert cancelled.revision == plan.revision + 1

        revoke_and_commit(
            revoker,
            organization_id=organization_id,
            representation_id=representation_id,
        )
        assert admin_conn.execute(
            """
            SELECT status, revision
            FROM request_engine.reminder_plans
            WHERE organization_id = %s AND id = %s
            """,
            (organization_id, plan.id),
        ).fetchone() == ("cancelled", plan.revision + 1)
        assert admin_conn.execute(
            """
            SELECT count(*)
            FROM request_engine.scheduled_actions
            WHERE organization_id = %s
              AND subject_kind = 'ReminderPlan'
              AND subject_id = %s
              AND status = 'pending'
            """,
            (organization_id, plan.id),
        ).fetchone() == (0,)
    finally:
        if not blocker.closed:
            blocker.rollback()
        if not revoker.closed:
            revoker.rollback()
        blocker.close()
        revoker.close()


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_reminders_manage_revoke_first_blocks_material_command(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    organization_id, principal_id, commands, plan, representation_id = await _active_plan(
        admin_conn,
        app_session_factory,
    )
    revoker = connect()
    try:
        begin_revoke(
            revoker,
            organization_id=organization_id,
            representation_id=representation_id,
        )
        task = asyncio.create_task(
            cancel_reminder_plan(
                commands,
                _cancel_command(
                    organization_id=organization_id,
                    principal_id=principal_id,
                    plan=plan,
                    key=f"reminder-manage-revoke-first-{uuid4().hex}",
                ),
            )
        )
        await wait_until_authority_blocked(admin_conn)
        revoker.commit()
        with pytest.raises(ReminderSubjectAuthorityRequired):
            await asyncio.wait_for(task, timeout=5)

        assert admin_conn.execute(
            """
            SELECT status, revision
            FROM request_engine.reminder_plans
            WHERE organization_id = %s AND id = %s
            """,
            (organization_id, plan.id),
        ).fetchone() == ("active", plan.revision)
        assert admin_conn.execute(
            """
            SELECT count(*)
            FROM request_engine.scheduled_actions
            WHERE organization_id = %s
              AND subject_kind = 'ReminderPlan'
              AND subject_id = %s
              AND status = 'pending'
            """,
            (organization_id, plan.id),
        ).fetchone() == (1,)
    finally:
        if not revoker.closed:
            revoker.rollback()
        revoker.close()
