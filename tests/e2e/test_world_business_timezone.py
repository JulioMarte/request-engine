from __future__ import annotations

import pytest

from e2e import f5_scheduled_assessment_support as assessment_support
from e2e.f4_capacity_support import seed_today_schedule
from e2e.f4_operational_day_support import configure_projection
from e2e.f5_booking_fixture import five_minute_sandbox
from e2e.f5_recovery_support import book_commitments, f5_actor, restrict_source_to_first_slots
from e2e.operational_support import PgConnection
from e2e.tenant_sandbox import TenantSandbox, client_with_actors, seed_tenant_sandbox
from e2e.world_clock import location_timezone, world_weekday
from request_engine.bootstrap.recovery_worker import build_recovery_assessment_handler
from request_engine.platform.db.session import SessionFactory

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.e2e,
    pytest.mark.postgres,
    pytest.mark.contract,
    pytest.mark.invariant,
]

FORCED_TIMEZONE = "Asia/Tokyo"


async def _tokyo_business_world(
    e2e_admin_conn: PgConnection, e2e_session_factory: SessionFactory, label: str
) -> TenantSandbox:
    sandbox = five_minute_sandbox(e2e_admin_conn, seed_tenant_sandbox(e2e_admin_conn, label))
    e2e_admin_conn.execute(
        "UPDATE request_engine.locations SET timezone=%s WHERE organization_id=%s AND id=%s",
        (FORCED_TIMEZONE, sandbox.organization_id, sandbox.location_id),
    )
    assert location_timezone(e2e_admin_conn, sandbox).key == FORCED_TIMEZONE
    seed_today_schedule(e2e_admin_conn, sandbox)
    actors = {sandbox.token: f5_actor(sandbox)}
    async with client_with_actors(e2e_session_factory, actors) as client:
        await configure_projection(client, sandbox)
        _, slots = await book_commitments(client, e2e_admin_conn, sandbox)
    restrict_source_to_first_slots(e2e_admin_conn, sandbox, slots, count=6)
    return sandbox


async def test_business_timezones_configured_far_from_the_runner_stay_material(
    e2e_admin_conn: PgConnection, e2e_session_factory: SessionFactory
) -> None:
    sandbox = await _tokyo_business_world(
        e2e_admin_conn, e2e_session_factory, "world-business-timezone"
    )
    assert location_timezone(e2e_admin_conn, sandbox).key == FORCED_TIMEZONE
    tokyo_weekday = world_weekday(e2e_admin_conn, sandbox)
    seeded = e2e_admin_conn.execute(
        "SELECT local_start,local_end FROM request_engine.availability_schedules "
        "WHERE organization_id=%s AND resource_id=%s AND weekday=%s",
        (sandbox.organization_id, sandbox.resource_id, tokyo_weekday),
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
