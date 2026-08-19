# pyright: reportPrivateUsage=false

import asyncio
from typing import Any
from uuid import uuid4

import pytest
from psycopg import Connection

from request_engine.modules.requests.adapters.db.request_commands import PostgresRequestCommands
from request_engine.modules.requests.application.commands.cancel_request import (
    CancelRequestCommand,
    cancel_request,
)
from request_engine.modules.requests.application.commands.create_request import create_request
from request_engine.modules.requests.application.errors import RequestPartyAuthorityRequired
from request_engine.modules.requests.contracts.request import RequestStatus
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
from .test_requests_core import _base_create_command, _create_fixture

PgConnection = Connection[Any]


async def _open_request(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
):
    fixture = _create_fixture(admin_conn)
    commands = PostgresRequestCommands(app_session_factory)
    created = await create_request(
        commands,
        _base_create_command(
            fixture,
            version_id=fixture.version_without_result_id,
            message="Party-authority manage race",
            idempotency_key=f"manage-race-create-{uuid4().hex}",
        ),
    )
    representation_id = create_representation(
        admin_conn,
        organization_id=fixture.organization_id,
        principal_id=fixture.principal_id,
        party_id=fixture.requester_party_id,
        scope_key="requests.manage",
    )
    return fixture, commands, created, representation_id


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_requests_manage_command_first_holds_authority_until_commit(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    fixture, commands, created, representation_id = await _open_request(
        admin_conn,
        app_session_factory,
    )
    blocker = connect()
    revoker = connect()
    try:
        lock_audit_barrier(blocker)
        task = asyncio.create_task(
            cancel_request(
                commands,
                CancelRequestCommand(
                    organization_id=fixture.organization_id,
                    principal_id=fixture.principal_id,
                    request_id=created.id,
                    expected_revision=created.revision,
                    reason="authority race command first",
                    idempotency_key=f"manage-race-cancel-{uuid4().hex}",
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
        assert cancelled.status is RequestStatus.CANCELLED
        assert cancelled.revision == created.revision + 1

        revoke_and_commit(
            revoker,
            organization_id=fixture.organization_id,
            representation_id=representation_id,
        )

        row = admin_conn.execute(
            """
            SELECT status, revision
            FROM request_engine.requests
            WHERE organization_id = %s AND id = %s
            """,
            (fixture.organization_id, created.id),
        ).fetchone()
        assert row == ("cancelled", created.revision + 1)
        assert admin_conn.execute(
            """
            SELECT count(*)
            FROM request_engine.outbox_messages
            WHERE organization_id = %s
              AND aggregate_kind = 'Request'
              AND aggregate_id = %s
              AND event_type = 'request.cancelled.v1'
            """,
            (fixture.organization_id, created.id),
        ).fetchone() == (1,)
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
async def test_requests_manage_revoke_first_blocks_material_command(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    fixture, commands, created, representation_id = await _open_request(
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
            cancel_request(
                commands,
                CancelRequestCommand(
                    organization_id=fixture.organization_id,
                    principal_id=fixture.principal_id,
                    request_id=created.id,
                    expected_revision=created.revision,
                    reason="authority race revoke first",
                    idempotency_key=f"manage-race-revoked-{uuid4().hex}",
                ),
            )
        )
        await wait_until_authority_blocked(admin_conn)
        revoker.commit()

        with pytest.raises(RequestPartyAuthorityRequired):
            await asyncio.wait_for(task, timeout=5)

        row = admin_conn.execute(
            """
            SELECT status, revision
            FROM request_engine.requests
            WHERE organization_id = %s AND id = %s
            """,
            (fixture.organization_id, created.id),
        ).fetchone()
        assert row == ("open", created.revision)
        assert admin_conn.execute(
            """
            SELECT count(*)
            FROM request_engine.outbox_messages
            WHERE organization_id = %s
              AND aggregate_kind = 'Request'
              AND aggregate_id = %s
              AND event_type = 'request.cancelled.v1'
            """,
            (fixture.organization_id, created.id),
        ).fetchone() == (0,)
    finally:
        if not revoker.closed:
            revoker.rollback()
        revoker.close()
