# pyright: reportPrivateUsage=false

import asyncio
from typing import Any
from uuid import uuid4

import pytest
from psycopg import Connection

from request_engine.modules.queue.adapters.db.waitlist_commands import PostgresWaitlistCommands
from request_engine.modules.queue.application.commands.join_waitlist import (
    JoinWaitlistCommand,
    join_waitlist,
)
from request_engine.modules.queue.application.commands.leave_waitlist import (
    LeaveWaitlistCommand,
    leave_waitlist,
)
from request_engine.modules.queue.application.errors import SubjectAuthorityRequired
from request_engine.modules.queue.contracts.waitlist import WaitlistEntryStatus
from request_engine.platform.db.session import SessionFactory

from ._authority_race_support import (
    assert_revoke_blocked,
    begin_revoke,
    connect,
    create_representation,
    lock_audit_barrier,
    revoke_and_commit,
    wait_until_audit_blocked,
    wait_until_authority_blocked,
)
from .test_http_waitlist import _fixture

PgConnection = Connection[Any]


async def _active_entry(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
):
    fixture = _fixture(admin_conn)
    commands = PostgresWaitlistCommands(app_session_factory)
    entry = await join_waitlist(
        commands,
        JoinWaitlistCommand(
            organization_id=fixture.organization_id,
            principal_id=fixture.principal_id,
            offering_id=fixture.offering_id,
            subject_party_id=fixture.subject_party_id,
            location_id=None,
            preferred_resource_id=None,
            earliest_start=None,
            latest_start=None,
            idempotency_key=f"waitlist-manage-join-{uuid4().hex}",
            allow_subject_override=True,
        ),
    )
    representation_id = create_representation(
        admin_conn,
        organization_id=fixture.organization_id,
        principal_id=fixture.principal_id,
        party_id=fixture.subject_party_id,
        scope_key="waitlist.manage",
    )
    return fixture, commands, entry, representation_id


def _leave_command(fixture, entry, *, key: str) -> LeaveWaitlistCommand:
    return LeaveWaitlistCommand(
        organization_id=fixture.organization_id,
        principal_id=fixture.principal_id,
        waitlist_entry_id=entry.id,
        expected_revision=entry.revision,
        reason="party-authority race",
        idempotency_key=key,
    )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_waitlist_manage_command_first_holds_authority_until_commit(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    fixture, commands, entry, representation_id = await _active_entry(
        admin_conn,
        app_session_factory,
    )
    blocker = connect()
    revoker = connect()
    try:
        lock_audit_barrier(blocker)
        task = asyncio.create_task(
            leave_waitlist(
                commands,
                _leave_command(
                    fixture,
                    entry,
                    key=f"waitlist-manage-command-first-{uuid4().hex}",
                ),
            )
        )
        await wait_until_audit_blocked(admin_conn)
        assert_revoke_blocked(
            revoker,
            organization_id=fixture.organization_id,
            representation_id=representation_id,
        )
        blocker.commit()
        cancelled = await asyncio.wait_for(task, timeout=5)
        assert cancelled.status is WaitlistEntryStatus.CANCELLED
        assert cancelled.revision == entry.revision + 1

        revoke_and_commit(
            revoker,
            organization_id=fixture.organization_id,
            representation_id=representation_id,
        )
        assert admin_conn.execute(
            """
            SELECT status, revision
            FROM request_engine.waitlist_entries
            WHERE organization_id = %s AND id = %s
            """,
            (fixture.organization_id, entry.id),
        ).fetchone() == ("cancelled", entry.revision + 1)
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
async def test_waitlist_manage_revoke_first_blocks_material_command(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    fixture, commands, entry, representation_id = await _active_entry(
        admin_conn,
        app_session_factory,
    )
    revoker = connect()
    try:
        begin_revoke(
            revoker,
            organization_id=fixture.organization_id,
            representation_id=representation_id,
        )
        task = asyncio.create_task(
            leave_waitlist(
                commands,
                _leave_command(
                    fixture,
                    entry,
                    key=f"waitlist-manage-revoke-first-{uuid4().hex}",
                ),
            )
        )
        await wait_until_authority_blocked(admin_conn)
        revoker.commit()
        with pytest.raises(SubjectAuthorityRequired):
            await asyncio.wait_for(task, timeout=5)

        assert admin_conn.execute(
            """
            SELECT status, revision
            FROM request_engine.waitlist_entries
            WHERE organization_id = %s AND id = %s
            """,
            (fixture.organization_id, entry.id),
        ).fetchone() == ("active", entry.revision)
    finally:
        if not revoker.closed:
            revoker.rollback()
        revoker.close()
