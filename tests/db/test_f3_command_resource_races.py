import asyncio

import pytest
from f3_command_race_support import align_fixture_to_db_clock, assert_one_winner, effects
from f3_live_ops_fixture import PgConnection, create_live_ops_fixture
from f3_live_ops_race_support import create_paused_session, create_principal

from request_engine.modules.delivery.adapters.db.live_service_operations import (
    PostgresLiveServiceOperations,
)
from request_engine.modules.delivery.application.resource_activity_commands import (
    StartResourceActivityCommand,
)
from request_engine.modules.delivery.application.service_session_commands import (
    CompleteServiceCommand,
    ResumeServiceCommand,
    StartServiceCommand,
)
from request_engine.modules.delivery.contracts.service_session import (
    ResourceActivity,
    ResourceActivityKind,
    ServiceSession,
)
from request_engine.platform.db.session import SessionFactory


@pytest.mark.asyncio
@pytest.mark.postgres
@pytest.mark.concurrency
@pytest.mark.adversarial
async def test_resume_complete_commands_serialize_without_partial_effects(
    admin_conn: PgConnection, command_session_factory: SessionFactory
) -> None:
    setup = create_live_ops_fixture(admin_conn)
    align_fixture_to_db_clock(admin_conn, setup)
    session_id, principal = create_paused_session(admin_conn, setup)
    operations = PostgresLiveServiceOperations(command_session_factory)
    resume = ResumeServiceCommand(
        setup.organization_id, principal, session_id, 2, "resume-complete-resume"
    )
    complete = CompleteServiceCommand(
        setup.organization_id,
        principal,
        session_id,
        2,
        "resume-complete-complete",
        setup.actual_workload_id,
    )
    results = await asyncio.gather(
        operations.resume_service(resume),
        operations.complete_service(complete),
        return_exceptions=True,
    )
    assert_one_winner(results, (ServiceSession,))
    row = admin_conn.execute(
        "SELECT status,revision FROM request_engine.service_sessions WHERE id=%s", (session_id,)
    ).fetchone()
    assert row == ("active", 3)
    assert effects(
        admin_conn, setup.organization_id, "service_session.resume", "service_session.resumed.v1"
    ) == (1, 1)
    assert effects(
        admin_conn,
        setup.organization_id,
        "service_session.complete",
        "service_session.completed.v1",
    ) == (0, 0)


@pytest.mark.asyncio
@pytest.mark.postgres
@pytest.mark.concurrency
@pytest.mark.adversarial
async def test_session_vs_resource_activity_commands_have_one_effectful_winner(
    admin_conn: PgConnection, command_session_factory: SessionFactory
) -> None:
    setup = create_live_ops_fixture(admin_conn)
    align_fixture_to_db_clock(admin_conn, setup)
    principal = create_principal(admin_conn, setup)
    operations = PostgresLiveServiceOperations(command_session_factory)
    start = StartServiceCommand(
        setup.organization_id,
        principal,
        setup.entry_a_id,
        setup.resource_id,
        setup.location_id,
        1,
        "session-activity-session",
        setup.actual_workload_id,
    )
    activity = StartResourceActivityCommand(
        setup.organization_id,
        principal,
        setup.resource_id,
        ResourceActivityKind.BREAK,
        "session-activity-activity",
        setup.location_id,
    )
    results = await asyncio.gather(
        operations.start_service(start),
        operations.start_resource_activity(activity),
        return_exceptions=True,
    )
    assert_one_winner(results, (ServiceSession, ResourceActivity))
    sessions = admin_conn.execute(
        "SELECT count(*) FROM request_engine.service_sessions "
        "WHERE resource_id=%s AND status IN ('active','paused')",
        (setup.resource_id,),
    ).fetchone()
    activities = admin_conn.execute(
        "SELECT count(*) FROM request_engine.resource_activities "
        "WHERE resource_id=%s AND ended_at IS NULL",
        (setup.resource_id,),
    ).fetchone()
    assert sessions is not None and activities is not None
    assert sessions[0] + activities[0] == 1
    if sessions == (1,):
        winner = ("service_session.start", "service_session.started.v1")
        loser = ("resource_activity.start", "resource_activity.started.v1")
    else:
        winner = ("resource_activity.start", "resource_activity.started.v1")
        loser = ("service_session.start", "service_session.started.v1")
    assert effects(admin_conn, setup.organization_id, *winner) == (1, 1)
    assert effects(admin_conn, setup.organization_id, *loser) == (0, 0)
