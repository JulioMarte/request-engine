import asyncio

import pytest
from f3_command_race_support import (
    align_fixture_to_db_clock,
    assert_idempotency_outcome,
    assert_one_winner,
    effects,
)
from f3_live_ops_fixture import PgConnection, create_live_ops_fixture
from f3_live_ops_race_support import create_active_session, create_principal

from request_engine.modules.delivery.adapters.db.live_service_operations import (
    PostgresLiveServiceOperations,
)
from request_engine.modules.delivery.application.service_session_commands import PauseServiceCommand
from request_engine.modules.delivery.contracts.service_session import (
    InterruptionKind,
    ServiceSession,
)
from request_engine.platform.db.session import SessionFactory


@pytest.mark.asyncio
@pytest.mark.postgres
@pytest.mark.concurrency
@pytest.mark.adversarial
async def test_pause_pause_commands_create_one_interruption_and_one_effect(
    admin_conn: PgConnection, command_session_factory: SessionFactory
) -> None:
    setup = create_live_ops_fixture(admin_conn)
    align_fixture_to_db_clock(admin_conn, setup)
    principal = create_principal(admin_conn, setup)
    session_id = create_active_session(admin_conn, setup, setup.entry_a_id)
    operations = PostgresLiveServiceOperations(command_session_factory)
    keys = ("pause-race-1", "pause-race-2")
    commands = [
        PauseServiceCommand(
            setup.organization_id,
            principal,
            session_id,
            1,
            InterruptionKind.BREAK,
            key,
        )
        for key in keys
    ]
    results = await asyncio.gather(
        *(operations.pause_service(command) for command in commands), return_exceptions=True
    )
    assert_one_winner(results, (ServiceSession,))
    winner_index = next(i for i, result in enumerate(results) if isinstance(result, ServiceSession))
    loser_index = 1 - winner_index
    session = admin_conn.execute(
        "SELECT status,revision FROM request_engine.service_sessions WHERE id=%s", (session_id,)
    ).fetchone()
    interruptions = admin_conn.execute(
        "SELECT count(*) FROM request_engine.service_session_interruptions "
        "WHERE service_session_id=%s AND ended_at IS NULL",
        (session_id,),
    ).fetchone()
    assert session == ("paused", 2) and interruptions == (1,)
    assert effects(
        admin_conn, setup.organization_id, "service_session.pause", "service_session.paused.v1"
    ) == (1, 1)
    assert_idempotency_outcome(
        admin_conn, setup.organization_id, principal, keys[winner_index], keys[loser_index]
    )
