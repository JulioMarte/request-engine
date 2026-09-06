from __future__ import annotations

import pytest

from e2e import f5_scheduled_assessment_support as assessment_support
from e2e.f4_capacity_support import seed_today_schedule
from e2e.f4_operational_day_support import configure_projection
from e2e.f5_booking_fixture import five_minute_sandbox
from e2e.f5_recovery_support import book_commitments, f5_actor, restrict_source_to_first_slots
from e2e.operational_support import PgConnection
from e2e.tenant_sandbox import TenantSandbox, client_with_actors, seed_tenant_sandbox
from e2e.world_clock import location_timezone, pick_far_business_timezone, world_weekday
from request_engine.bootstrap.recovery_worker import build_recovery_assessment_handler
from request_engine.platform.db.session import SessionFactory

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.e2e,
    pytest.mark.postgres,
    pytest.mark.contract,
    pytest.mark.invariant,
]


async def _far_business_world(
    e2e_admin_conn: PgConnection, e2e_session_factory: SessionFactory, label: str
) -> tuple[TenantSandbox, str]:
    sandbox = five_minute_sandbox(e2e_admin_conn, seed_tenant_sandbox(e2e_admin_conn, label))
    forced_timezone = pick_far_business_timezone(e2e_admin_conn)
    seed_today_schedule(e2e_admin_conn, sandbox, business_timezone=forced_timezone)
    assert location_timezone(e2e_admin_conn, sandbox).key == forced_timezone
    actors = {sandbox.token: f5_actor(sandbox)}
    async with client_with_actors(e2e_session_factory, actors) as client:
        await configure_projection(client, sandbox)
        _, slots = await book_commitments(client, e2e_admin_conn, sandbox)
    restrict_source_to_first_slots(e2e_admin_conn, sandbox, slots, count=6)
    return sandbox, forced_timezone


async def test_business_timezones_configured_far_from_the_runner_stay_material(
    e2e_admin_conn: PgConnection, e2e_session_factory: SessionFactory
) -> None:
    sandbox, forced_timezone = await _far_business_world(
        e2e_admin_conn, e2e_session_factory, "world-business-timezone"
    )
    assert location_timezone(e2e_admin_conn, sandbox).key == forced_timezone
    assert forced_timezone != "America/Santo_Domingo"
    local_weekday = world_weekday(e2e_admin_conn, sandbox)
    seeded = e2e_admin_conn.execute(
        "SELECT availability.local_start,availability.local_end "
        "FROM request_engine.resource_location_availability AS availability "
        "JOIN request_engine.resource_location_assignments AS assignment "
        "ON assignment.organization_id=availability.organization_id "
        "AND assignment.id=availability.resource_location_assignment_id "
        "WHERE availability.organization_id=%s AND assignment.resource_id=%s "
        "AND assignment.location_id=%s AND availability.weekday=%s",
        (
            sandbox.organization_id,
            sandbox.resource_id,
            sandbox.location_id,
            local_weekday,
        ),
    ).fetchall()
    assert len(seeded) >= 1

    revision = assessment_support.current_source_revision(e2e_admin_conn, sandbox)
    lease = assessment_support.lease_reassessment(e2e_admin_conn, sandbox, revision)
    handler = build_recovery_assessment_handler(e2e_session_factory)
    commit = await handler.handle(lease)

    assert commit.applied is True and commit.incident is not None
    assert assessment_support.incident_revision(e2e_admin_conn, sandbox) == (
        revision,
        commit.incident.revision,
    )
