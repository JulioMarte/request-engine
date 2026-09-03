from datetime import UTC, datetime, time, timedelta

import pytest

from request_engine.platform.db.session import SessionFactory

from .f4_capacity_support import seed_today_schedule
from .f5_booking_fixture import five_minute_sandbox
from .f5_contextual_support import contextualize_recovery_supply
from .f5_extend_day_fixture import grant_extend_day_authority
from .f5_extend_day_support import assignment_recovery_exception_count, owner_revisions
from .f6_adversarial_concurrency_support import concurrent_conflicting_posts
from .f6_copilot_support import copilot_actor, read_tool
from .f6_roadmap_support import seed_location_operational_hours, seed_publishable_discovery_world
from .operational_support import PgConnection
from .tenant_sandbox import client_with_actors, seed_tenant_sandbox
from .world_clock import location_timezone, world_weekday, world_window_start

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.e2e,
    pytest.mark.postgres,
    pytest.mark.contract,
    pytest.mark.adversarial,
]


async def test_f6_concurrent_same_key_different_intake_payload_has_one_winner(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = five_minute_sandbox(
        e2e_admin_conn, seed_tenant_sandbox(e2e_admin_conn, "f6-race-intake")
    )
    actors = {sandbox.token: copilot_actor(sandbox)}
    async with client_with_actors(e2e_session_factory, actors) as client:
        intake = await read_tool(client, sandbox, f"/queues/{sandbox.queue_id}/intake")
        common = {
            "service_queue_id": str(sandbox.queue_id),
            "accepting": False,
            "expected_intake_revision": intake["revision"],
            "reason": "adversarial conflicting replay",
        }
        now = datetime.now(UTC)
        await concurrent_conflicting_posts(
            client,
            sandbox,
            "/queues/intake-control",
            {**common, "effective_until": (now + timedelta(hours=1)).isoformat()},
            {**common, "effective_until": (now + timedelta(hours=2)).isoformat()},
        )
    row = e2e_admin_conn.execute(
        "SELECT count(*), max(revision) FROM request_engine.service_queue_intake_controls "
        "WHERE organization_id=%s AND service_queue_id=%s",
        (sandbox.organization_id, sandbox.queue_id),
    ).fetchone()
    assert row == (1, intake["revision"] + 1)


async def test_f6_concurrent_same_key_different_extension_has_one_winner(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = five_minute_sandbox(
        e2e_admin_conn, seed_tenant_sandbox(e2e_admin_conn, "f6-race-extension")
    )
    grant_extend_day_authority(e2e_admin_conn, sandbox)
    seed_today_schedule(e2e_admin_conn, sandbox)
    seed_location_operational_hours(e2e_admin_conn, sandbox)
    supply = contextualize_recovery_supply(e2e_admin_conn, sandbox)
    e2e_admin_conn.execute(
        "UPDATE request_engine.resource_location_availability SET local_end='17:00' "
        "WHERE organization_id=%s AND resource_location_assignment_id=%s AND weekday=%s",
        (sandbox.organization_id, supply.assignment_id, world_weekday(e2e_admin_conn, sandbox)),
    )
    zone = location_timezone(e2e_admin_conn, sandbox)
    local_day = world_window_start(e2e_admin_conn).astimezone(zone).date()
    _, revision = owner_revisions(e2e_admin_conn, sandbox)
    common = {
        "assignment_id": str(supply.assignment_id),
        "start_at": datetime.combine(local_day, time(17), tzinfo=zone).isoformat(),
        "expected_resource_availability_revision": revision,
        "reason": "adversarial conflicting replay",
    }
    actors = {sandbox.token: copilot_actor(sandbox)}
    async with client_with_actors(e2e_session_factory, actors) as client:
        await concurrent_conflicting_posts(
            client,
            sandbox,
            "/assignments/day-extensions",
            {**common, "end_at": datetime.combine(local_day, time(19), tzinfo=zone).isoformat()},
            {**common, "end_at": datetime.combine(local_day, time(20), tzinfo=zone).isoformat()},
        )
    assert assignment_recovery_exception_count(e2e_admin_conn, sandbox, supply.assignment_id) == 1
    assert owner_revisions(e2e_admin_conn, sandbox)[1] == revision + 1


async def test_f6_concurrent_same_key_different_publication_has_one_winner(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = seed_tenant_sandbox(e2e_admin_conn, "f6-race-discovery")
    seed_publishable_discovery_world(e2e_admin_conn, sandbox)
    start = datetime.now(UTC) - timedelta(minutes=1)
    common = {
        "offering_id": str(sandbox.offering_id),
        "location_id": str(sandbox.location_id),
        "resource_id": str(sandbox.resource_id),
        "effective_start": start.isoformat(),
        "provider_visibility": "public",
    }
    actors = {sandbox.token: copilot_actor(sandbox)}
    async with client_with_actors(e2e_session_factory, actors) as client:
        await concurrent_conflicting_posts(
            client,
            sandbox,
            "/discovery/publications",
            {**common, "effective_end": (start + timedelta(days=1)).isoformat()},
            {**common, "effective_end": (start + timedelta(days=2)).isoformat()},
        )
    row = e2e_admin_conn.execute(
        "SELECT count(*) FROM request_engine.discovery_publications "
        "WHERE organization_id=%s AND offering_id=%s",
        (sandbox.organization_id, sandbox.offering_id),
    ).fetchone()
    assert row == (1,)
