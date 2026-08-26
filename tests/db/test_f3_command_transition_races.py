import asyncio

import pytest
from f3_command_race_support import assert_one_winner, effects
from f3_live_ops_fixture import PgConnection, create_live_ops_fixture
from f3_live_ops_race_support import create_active_session, create_principal

from request_engine.modules.delivery.adapters.db.live_service_operations import (
    PostgresLiveServiceOperations,
)
from request_engine.modules.delivery.application.service_session_commands import (
    PauseServiceCommand,
    StartServiceCommand,
)
from request_engine.modules.delivery.contracts.service_session import (
    InterruptionKind,
    ServiceSession,
)
from request_engine.modules.queue.adapters.db.live_queue_commands import (
    PostgresLiveQueueCommands,
)
from request_engine.modules.queue.application.live_commands import MarkNoShowCommand
from request_engine.modules.queue.contracts.live_queue import LiveQueueEntry
from request_engine.platform.db.session import SessionFactory


@pytest.mark.asyncio
@pytest.mark.postgres
@pytest.mark.concurrency
@pytest.mark.adversarial
async def test_start_service_vs_no_show_commands_have_one_effectful_winner(
    admin_conn: PgConnection, command_session_factory: SessionFactory
) -> None:
    setup = create_live_ops_fixture(admin_conn)
    principal = create_principal(admin_conn, setup)
    delivery = PostgresLiveServiceOperations(command_session_factory)
    queue = PostgresLiveQueueCommands(command_session_factory)
    start = StartServiceCommand(
        setup.organization_id,
        principal,
        setup.entry_a_id,
        setup.resource_id,
        setup.location_id,
        1,
        "command-start-no-show-start",
        setup.actual_workload_id,
    )
    no_show = MarkNoShowCommand(
        setup.organization_id, principal, setup.entry_a_id, 1, "command-start-no-show-no-show"
    )
    results = await asyncio.gather(
        delivery.start_service(start), queue.mark_no_show(no_show), return_exceptions=True
    )
    assert_one_winner(results, (ServiceSession, LiveQueueEntry))
    row = admin_conn.execute(
        "SELECT status FROM request_engine.queue_entries WHERE id=%s", (setup.entry_a_id,)
    ).fetchone()
    sessions = admin_conn.execute(
        "SELECT count(*) FROM request_engine.service_sessions WHERE queue_entry_id=%s",
        (setup.entry_a_id,),
    ).fetchone()
    assert row is not None and sessions is not None
    if row[0] == "serving":
        assert sessions == (1,)
        winner = ("service_session.start", "service_session.started.v1")
        loser = ("queue.mark_no_show", "queue.entry.no_show.v1")
    else:
        assert row[0] == "no_show" and sessions == (0,)
        winner = ("queue.mark_no_show", "queue.entry.no_show.v1")
        loser = ("service_session.start", "service_session.started.v1")
    assert effects(admin_conn, setup.organization_id, *winner) == (1, 1)
    assert effects(admin_conn, setup.organization_id, *loser) == (0, 0)


@pytest.mark.asyncio
@pytest.mark.postgres
@pytest.mark.concurrency
@pytest.mark.adversarial
async def test_pause_pause_commands_create_one_interruption_and_one_effect(
    admin_conn: PgConnection, command_session_factory: SessionFactory
) -> None:
    setup = create_live_ops_fixture(admin_conn)
    principal = create_principal(admin_conn, setup)
    session_id = create_active_session(admin_conn, setup, setup.entry_a_id)
    operations = PostgresLiveServiceOperations(command_session_factory)
    commands = [
        PauseServiceCommand(
            setup.organization_id,
            principal,
            session_id,
            1,
            InterruptionKind.BREAK,
            f"pause-race-{index}",
        )
        for index in (1, 2)
    ]
    results = await asyncio.gather(
        *(operations.pause_service(command) for command in commands), return_exceptions=True
    )
    assert_one_winner(results, (ServiceSession,))
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
