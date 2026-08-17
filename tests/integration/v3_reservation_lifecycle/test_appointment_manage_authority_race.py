# pyright: reportPrivateUsage=false

import asyncio
from typing import Any
from uuid import UUID, uuid4

import pytest
from psycopg import Connection

from request_engine.modules.booking.adapters.db.reservation_commands import (
    PostgresReservationCommands,
)
from request_engine.modules.booking.application.commands.cancel_reservation import (
    CancelReservationCommand,
    cancel_reservation,
)
from request_engine.modules.booking.application.errors import SubjectAuthorityRequired
from request_engine.modules.booking.contracts.appointments import ReservationStatus
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
from .test_reservation_lifecycle import LifecycleFixture, _fixture, _future_start

PgConnection = Connection[Any]


async def _confirmed_reservation(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> tuple[LifecycleFixture, PostgresReservationCommands, UUID]:
    fixture = _fixture(
        admin_conn,
        policy={},
        start_at=_future_start(),
    )
    representation_id = create_representation(
        admin_conn,
        organization_id=fixture.organization_id,
        principal_id=fixture.principal_id,
        party_id=fixture.subject_id,
    )
    return fixture, PostgresReservationCommands(app_session_factory), representation_id


def _cancel_command(fixture: LifecycleFixture, *, key: str) -> CancelReservationCommand:
    return CancelReservationCommand(
        organization_id=fixture.organization_id,
        principal_id=fixture.principal_id,
        reservation_id=fixture.reservation_id,
        expected_revision=1,
        reason="party-authority race",
        idempotency_key=key,
    )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_appointments_manage_command_first_holds_authority_until_commit(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    fixture, commands, representation_id = await _confirmed_reservation(
        admin_conn,
        app_session_factory,
    )
    blocker = connect()
    revoker = connect()
    try:
        lock_audit_barrier(blocker)
        task = asyncio.create_task(
            cancel_reservation(
                commands,
                _cancel_command(
                    fixture,
                    key=f"appointment-manage-command-first-{uuid4().hex}",
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
        assert cancelled.status is ReservationStatus.CANCELLED
        assert cancelled.revision == 2

        revoke_and_commit(
            revoker,
            organization_id=fixture.organization_id,
            representation_id=representation_id,
        )
        assert admin_conn.execute(
            """
            SELECT status, revision
            FROM request_engine.reservations
            WHERE organization_id = %s AND id = %s
            """,
            (fixture.organization_id, fixture.reservation_id),
        ).fetchone() == ("cancelled", 2)
        assert admin_conn.execute(
            """
            SELECT count(*)
            FROM request_engine.capacity_claims
            WHERE organization_id = %s
              AND reservation_id = %s
              AND status = 'active'
            """,
            (fixture.organization_id, fixture.reservation_id),
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
async def test_appointments_manage_revoke_first_blocks_material_command(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    fixture, commands, representation_id = await _confirmed_reservation(
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
            cancel_reservation(
                commands,
                _cancel_command(
                    fixture,
                    key=f"appointment-manage-revoke-first-{uuid4().hex}",
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
            FROM request_engine.reservations
            WHERE organization_id = %s AND id = %s
            """,
            (fixture.organization_id, fixture.reservation_id),
        ).fetchone() == ("confirmed", 1)
        assert admin_conn.execute(
            """
            SELECT count(*)
            FROM request_engine.capacity_claims
            WHERE organization_id = %s
              AND reservation_id = %s
              AND status = 'active'
            """,
            (fixture.organization_id, fixture.reservation_id),
        ).fetchone() == (1,)
    finally:
        if not revoker.closed:
            revoker.rollback()
        revoker.close()
