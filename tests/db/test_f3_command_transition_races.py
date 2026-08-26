import asyncio
from uuid import UUID

import pytest
from f3_live_ops_fixture import PgConnection, create_live_ops_fixture
from f3_live_ops_race_support import create_active_session, create_paused_session, create_principal

from request_engine.modules.delivery.adapters.db.live_service_operations import PostgresLiveServiceOperations
from request_engine.modules.delivery.application.resource_activity_commands import StartResourceActivityCommand
from request_engine.modules.delivery.application.service_session_commands import (
    CompleteServiceCommand,
    PauseServiceCommand,
    ResumeServiceCommand,
    StartServiceCommand,
)
from request_engine.modules.delivery.contracts.service_session import (
    InterruptionKind,
    ResourceActivity,
    ResourceActivityKind,
    ServiceSession,
)
from request_engine.modules.queue.adapters.db.live_queue_commands import PostgresLiveQueueCommands
from request_engine.modules.queue.application.live_commands import MarkNoShowCommand
from request_engine.modules.queue.contracts.live_queue import LiveQueueEntry
from request_engine.platform.db.session import SessionFactory


def _effect_count(conn: PgConnection, organization_id: UUID, *, command: str, event: str) -> tuple[int, int]:
    audit = conn.execute(
        "SELECT count(*) FROM request_engine.audit_records WHERE organization_id=%s AND command_name=%s",
        (organization_id, command),
    ).fetchone()
    outbox = conn.execute(
        "SELECT count(*) FROM request_engine.outbox_messages WHERE organization_id=%s AND event_type=%s",
        (organization_id, event),
    ).fetchone()
    assert audit is not None and outbox is not None
    return audit[0], outbox[0]


@pytest.mark.asyncio
@pytest.mark.postgres
@pytest.mark.concurrency
@pytest.mark.adversarial
async def test_start_service_vs_no_show_commands_have_one_effectful_winner(
    admin_conn: PgConnection, command_session_factory: SessionFactory
) -> None:
    setup = create_live_ops_fixture(admin_conn)
    principal_id = create_principal(admin_conn, setup)
    delivery = PostgresLiveServiceOperations(command_session_factory)
    queue = PostgresLiveQueueCommands(command_session_factory)
    start = StartServiceCommand(
        organization_id=setup.organization_id,
        principal_id=principal_id,
        queue_entry_id=setup.entry_a_id,
        resource_id=setup.resource_id,
        location_id=setup.location_id,
        expected_queue_revision=1,
        idempotency_key="command-start-no-show-start",
        actual_workload_classification_id=setup.actual_workload_id,
    )
    no_show = MarkNoShowCommand(
        organization_id=setup.organization_id,
        principal_id=principal_id,
        queue_entry_id=setup.entry_a_id,
        expected_revision=1,
        idempotency_key="command-start-no-show-no-show",
    )
    results = await asyncio.gather(
        delivery.start_service(start), queue.mark_no_show(no_show), return_exceptions=True
    )
    assert sum(isinstance(result, (ServiceSession, LiveQueueEntry)) for result in results) == 1
    assert sum(isinstance(result, Exception) for result in results) == 1
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
        assert _effect_count(admin_conn, setup.organization_id, command="service_session.start", event="service_session.started.v1") == (1, 1)
        assert _effect_count(admin_conn, setup.organization_id, command="queue.mark_no_show", event="queue.entry.no_show.v1") == (0, 0)
    else:
        assert row[0] == "no_show" and sessions == (0,)
        assert _effect_count(admin_conn, setup.organization_id, command="queue.mark_no_show", event="queue.entry.no_show.v1") == (1, 1)
        assert _effect_count(admin_conn, setup.organization_id, command="service_session.start", event="service_session.started.v1") == (0, 0)


@pytest.mark.asyncio
@pytest.mark.postgres
@pytest.mark.concurrency
@pytest.mark.adversarial
async def test_pause_pause_commands_create_one_interruption_and_one_effect(
    admin_conn: PgConnection, command_session_factory: SessionFactory
) -> None:
    setup = create_live_ops_fixture(admin_conn)
    principal_id = create_principal(admin_conn, setup)
    session_id = create_active_session(admin_conn, setup, setup.entry_a_id)
    operations = PostgresLiveServiceOperations(command_session_factory)
    commands = [
        PauseServiceCommand(setup.organization_id, principal_id, session_id, 1, InterruptionKind.BREAK, f"pause-race-{index}")
        for index in (1, 2)
    ]
    results = await asyncio.gather(*(operations.pause_service(command) for command in commands), return_exceptions=True)
    assert sum(isinstance(result, ServiceSession) for result in results) == 1
    assert sum(isinstance(result, Exception) for result in results) == 1
    session = admin_conn.execute("SELECT status,revision FROM request_engine.service_sessions WHERE id=%s", (session_id,)).fetchone()
    interruptions = admin_conn.execute("SELECT count(*) FROM request_engine.service_session_interruptions WHERE service_session_id=%s AND ended_at IS NULL", (session_id,)).fetchone()
    assert session == ("paused", 2)
    assert interruptions == (1,)
    assert _effect_count(admin_conn, setup.organization_id, command="service_session.pause", event="service_session.paused.v1") == (1, 1)


@pytest.mark.asyncio
@pytest.mark.postgres
@pytest.mark.concurrency
@pytest.mark.adversarial
async def test_resume_complete_commands_serialize_without_partial_effects(
    admin_conn: PgConnection, command_session_factory: SessionFactory
) -> None:
    setup = create_live_ops_fixture(admin_conn)
    session_id, principal_id = create_paused_session(admin_conn, setup)
    operations = PostgresLiveServiceOperations(command_session_factory)
    results = await asyncio.gather(
        operations.resume_service(ResumeServiceCommand(setup.organization_id, principal_id, session_id, 2, "resume-complete-resume")),
        operations.complete_service(CompleteServiceCommand(setup.organization_id, principal_id, session_id, 2, "resume-complete-complete", setup.actual_workload_id)),
        return_exceptions=True,
    )
    assert sum(isinstance(result, ServiceSession) for result in results) == 1
    assert sum(isinstance(result, Exception) for result in results) == 1
    row = admin_conn.execute("SELECT status,revision FROM request_engine.service_sessions WHERE id=%s", (session_id,)).fetchone()
    assert row is not None
    # Complete requires ACTIVE; from the shared PAUSED revision only Resume may win.
    assert row == ("active", 3)
    assert _effect_count(admin_conn, setup.organization_id, command="service_session.resume", event="service_session.resumed.v1") == (1, 1)
    assert _effect_count(admin_conn, setup.organization_id, command="service_session.complete", event="service_session.completed.v1") == (0, 0)


@pytest.mark.asyncio
@pytest.mark.postgres
@pytest.mark.concurrency
@pytest.mark.adversarial
async def test_session_vs_resource_activity_commands_have_one_effectful_winner(
    admin_conn: PgConnection, command_session_factory: SessionFactory
) -> None:
    setup = create_live_ops_fixture(admin_conn)
    principal_id = create_principal(admin_conn, setup)
    operations = PostgresLiveServiceOperations(command_session_factory)
    results = await asyncio.gather(
        operations.start_service(StartServiceCommand(setup.organization_id, principal_id, setup.entry_a_id, setup.resource_id, setup.location_id, 1, "session-activity-session", setup.actual_workload_id)),
        operations.start_resource_activity(StartResourceActivityCommand(setup.organization_id, principal_id, setup.resource_id, ResourceActivityKind.BREAK, "session-activity-activity", setup.location_id)),
        return_exceptions=True,
    )
    assert sum(isinstance(result, (ServiceSession, ResourceActivity)) for result in results) == 1
    assert sum(isinstance(result, Exception) for result in results) == 1
    live_sessions = admin_conn.execute("SELECT count(*) FROM request_engine.service_sessions WHERE resource_id=%s AND status IN ('active','paused')", (setup.resource_id,)).fetchone()
    open_activities = admin_conn.execute("SELECT count(*) FROM request_engine.resource_activities WHERE resource_id=%s AND ended_at IS NULL", (setup.resource_id,)).fetchone()
    assert live_sessions is not None and open_activities is not None
    assert live_sessions[0] + open_activities[0] == 1
    if live_sessions == (1,):
        assert _effect_count(admin_conn, setup.organization_id, command="service_session.start", event="service_session.started.v1") == (1, 1)
        assert _effect_count(admin_conn, setup.organization_id, command="resource_activity.start", event="resource_activity.started.v1") == (0, 0)
    else:
        assert _effect_count(admin_conn, setup.organization_id, command="resource_activity.start", event="resource_activity.started.v1") == (1, 1)
        assert _effect_count(admin_conn, setup.organization_id, command="service_session.start", event="service_session.started.v1") == (0, 0)
