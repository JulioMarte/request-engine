# pyright: reportPrivateUsage=false

import asyncio
from typing import Any
from uuid import UUID, uuid4

import pytest
from psycopg import Connection

from request_engine.modules.queue.adapters.db.leave_queue_commands import (
    PostgresLeaveQueueCommands,
)
from request_engine.modules.queue.adapters.db.service_queue_commands import (
    PostgresServiceQueueCommands,
)
from request_engine.modules.queue.application.commands.join_queue import (
    JoinQueueCommand,
    join_queue,
)
from request_engine.modules.queue.application.commands.leave_queue import (
    LeaveQueueCommand,
    leave_queue,
)
from request_engine.modules.queue.application.errors import SubjectAuthorityRequired
from request_engine.modules.queue.contracts.service_queue import QueueEntry, QueueEntryStatus
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
from .test_business_and_queue import (
    _create_organization,
    _create_party,
    _create_principal,
    _create_queue,
)

PgConnection = Connection[Any]


async def _waiting_entry(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> tuple[UUID, UUID, UUID, UUID, QueueEntry, UUID]:
    organization_id = _create_organization(admin_conn)
    principal_id = _create_principal(admin_conn, organization_id)
    queue_id = _create_queue(admin_conn, organization_id)
    subject_party_id = _create_party(admin_conn, organization_id, "Queue authority subject")
    entry = await join_queue(
        PostgresServiceQueueCommands(app_session_factory),
        JoinQueueCommand(
            organization_id=organization_id,
            principal_id=principal_id,
            queue_id=queue_id,
            subject_party_id=subject_party_id,
            idempotency_key=f"queue-manage-join-{uuid4().hex}",
            allow_subject_override=True,
        ),
    )
    representation_id = create_representation(
        admin_conn,
        organization_id=organization_id,
        principal_id=principal_id,
        party_id=subject_party_id,
        scope_key="queue.manage",
    )
    return organization_id, principal_id, queue_id, subject_party_id, entry, representation_id


def _leave_command(
    *,
    organization_id: UUID,
    principal_id: UUID,
    queue_id: UUID,
    entry: QueueEntry,
    key: str,
) -> LeaveQueueCommand:
    return LeaveQueueCommand(
        organization_id=organization_id,
        principal_id=principal_id,
        queue_id=queue_id,
        queue_entry_id=entry.id,
        expected_revision=entry.revision,
        reason="party-authority race",
        idempotency_key=key,
    )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_queue_manage_command_first_holds_authority_until_commit(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    organization_id, principal_id, queue_id, _, entry, representation_id = await _waiting_entry(
        admin_conn,
        app_session_factory,
    )
    commands = PostgresLeaveQueueCommands(app_session_factory)
    blocker = connect()
    revoker = connect()
    try:
        lock_audit_barrier(blocker)
        task = asyncio.create_task(
            leave_queue(
                commands,
                _leave_command(
                    organization_id=organization_id,
                    principal_id=principal_id,
                    queue_id=queue_id,
                    entry=entry,
                    key=f"queue-manage-command-first-{uuid4().hex}",
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
        assert cancelled.status is QueueEntryStatus.CANCELLED
        assert cancelled.revision == entry.revision + 1

        revoke_and_commit(
            revoker,
            organization_id=organization_id,
            representation_id=representation_id,
        )
        assert admin_conn.execute(
            """
            SELECT status, revision
            FROM request_engine.queue_entries
            WHERE organization_id = %s AND id = %s
            """,
            (organization_id, entry.id),
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
async def test_queue_manage_revoke_first_blocks_material_command(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    organization_id, principal_id, queue_id, _, entry, representation_id = await _waiting_entry(
        admin_conn,
        app_session_factory,
    )
    commands = PostgresLeaveQueueCommands(app_session_factory)
    revoker = connect()
    try:
        begin_revoke(
            revoker,
            organization_id=organization_id,
            representation_id=representation_id,
        )
        task = asyncio.create_task(
            leave_queue(
                commands,
                _leave_command(
                    organization_id=organization_id,
                    principal_id=principal_id,
                    queue_id=queue_id,
                    entry=entry,
                    key=f"queue-manage-revoke-first-{uuid4().hex}",
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
            FROM request_engine.queue_entries
            WHERE organization_id = %s AND id = %s
            """,
            (organization_id, entry.id),
        ).fetchone() == ("waiting", entry.revision)
    finally:
        if not revoker.closed:
            revoker.rollback()
        revoker.close()
