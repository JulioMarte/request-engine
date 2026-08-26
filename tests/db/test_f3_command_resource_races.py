import asyncio

import pytest
from f3_command_race_support import (
    align_fixture_to_db_clock,
    assert_idempotency_outcome,
    assert_one_winner,
    effects,
)
from f3_live_ops_fixture import PgConnection, create_live_ops_fixture
from f3_live_ops_race_support import create_principal

from request_engine.modules.delivery.adapters.db.live_service_operations import (
    PostgresLiveServiceOperations,
)
from request_engine.modules.delivery.application.errors import LiveServiceRevisionConflict
from request_engine.modules.delivery.application.resource_activity_commands import (
    StartResourceActivityCommand,
)
from request_engine.modules.delivery.application.service_session_commands import StartServiceCommand
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
async def test_session_vs_resource_activity_commands_have_one_effectful_winner(
    admin_conn: PgConnection, command_session_factory: SessionFactory
) -> None:
    setup = create_live_ops_fixture(admin_conn)
    revisions = align_fixture_to_db_clock(admin_conn, setup)
    principal = create_principal(admin_conn, setup)
    operations = PostgresLiveServiceOperations(command_session_factory)
    session_key = "session-activity-session"
    activity_key = "session-activity-activity"
    start = StartServiceCommand(
        setup.organization_id,
        principal,
        setup.entry_a_id,
        setup.resource_id,
        setup.location_id,
        revisions[setup.entry_a_id],
        session_key,
        setup.actual_workload_id,
    )
    activity = StartResourceActivityCommand(
        setup.organization_id,
        principal,
        setup.resource_id,
        ResourceActivityKind.BREAK,
        activity_key,
        setup.location_id,
    )
    results = await asyncio.gather(
        operations.start_service(start),
        operations.start_resource_activity(activity),
        return_exceptions=True,
    )
    assert_one_winner(results, (ServiceSession, ResourceActivity))
    assert not any(isinstance(result, LiveServiceRevisionConflict) for result in results), repr(
        results
    )
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
        winner_key, loser_key = session_key, activity_key
    else:
        winner = ("resource_activity.start", "resource_activity.started.v1")
        loser = ("service_session.start", "service_session.started.v1")
        winner_key, loser_key = activity_key, session_key
    assert effects(admin_conn, setup.organization_id, *winner) == (1, 1)
    assert effects(admin_conn, setup.organization_id, *loser) == (0, 0)
    assert_idempotency_outcome(admin_conn, setup.organization_id, principal, winner_key, loser_key)
