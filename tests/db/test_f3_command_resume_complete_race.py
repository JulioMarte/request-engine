import asyncio

import pytest
from f3_command_race_support import (
    align_fixture_to_db_clock,
    assert_idempotency_outcome,
    assert_one_winner,
    effects,
)
from f3_live_ops_fixture import PgConnection, create_live_ops_fixture
from f3_live_ops_race_support import create_paused_session

from request_engine.modules.delivery.adapters.db.live_service_operations import (
    PostgresLiveServiceOperations,
)
from request_engine.modules.delivery.application.service_session_commands import (
    CompleteServiceCommand,
    ResumeServiceCommand,
)
from request_engine.modules.delivery.contracts.service_session import ServiceSession
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
    resume_key = "resume-complete-resume"
    complete_key = "resume-complete-complete"
    resume = ResumeServiceCommand(
        setup.organization_id, principal, session_id, 2, resume_key
    )
    complete = CompleteServiceCommand(
        setup.organization_id,
        principal,
        session_id,
        2,
        complete_key,
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
    assert_idempotency_outcome(
        admin_conn, setup.organization_id, principal, resume_key, complete_key
    )
