import asyncio
from datetime import datetime, time
from uuid import uuid4

import pytest

from request_engine.platform.db.session import SessionFactory

from .f4_capacity_support import seed_today_schedule
from .f5_booking_fixture import five_minute_sandbox
from .f5_contextual_support import contextualize_recovery_supply
from .f5_extend_day_fixture import grant_extend_day_authority
from .f5_extend_day_support import assignment_recovery_exception_count, owner_revisions
from .f6_copilot_support import copilot_actor, read_tool
from .f6_roadmap_support import seed_location_operational_hours
from .operational_support import PgConnection
from .tenant_sandbox import auth, client_with_actors, seed_tenant_sandbox
from .world_clock import location_timezone, world_weekday, world_window_start

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.e2e,
    pytest.mark.postgres,
    pytest.mark.contract,
    pytest.mark.adversarial,
]


async def test_f6_concurrent_structured_intake_replays_once(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    base = seed_tenant_sandbox(e2e_admin_conn, "f6-concurrent-proactive-intake")
    sandbox = five_minute_sandbox(e2e_admin_conn, base)
    actors = {sandbox.token: copilot_actor(sandbox)}
    async with client_with_actors(e2e_session_factory, actors) as client:
        intake = await read_tool(client, sandbox, f"/queues/{sandbox.queue_id}/intake")
        body = {
            "service_queue_id": str(sandbox.queue_id),
            "accepting": False,
            "expected_intake_revision": intake["revision"],
            "reason": "operator closed walk-ins",
        }
        headers = auth(sandbox, idempotency_key=f"f6-concurrent-intake-{uuid4().hex}")
        path = "/v1/operational-copilot/tools/queues/intake-control"
        first, second = await asyncio.gather(
            client.post(path, json=body, headers=headers),
            client.post(path, json=body, headers=headers),
        )
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["result_id"] == second.json()["result_id"]
    row = e2e_admin_conn.execute(
        "SELECT accepting,revision FROM request_engine.service_queue_intake_controls "
        "WHERE organization_id=%s AND service_queue_id=%s",
        (sandbox.organization_id, sandbox.queue_id),
    ).fetchone()
    assert row is not None and row[0] is False and row[1] == intake["revision"] + 1


async def test_f6_concurrent_structured_extend_applies_once(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    base = seed_tenant_sandbox(e2e_admin_conn, "f6-concurrent-proactive-extend")
    sandbox = five_minute_sandbox(e2e_admin_conn, base)
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
    _, availability_revision = owner_revisions(e2e_admin_conn, sandbox)
    body = {
        "assignment_id": str(supply.assignment_id),
        "start_at": datetime.combine(local_day, time(17), tzinfo=zone).isoformat(),
        "end_at": datetime.combine(local_day, time(19), tzinfo=zone).isoformat(),
        "expected_resource_availability_revision": availability_revision,
        "reason": "operator extended today",
    }
    actors = {sandbox.token: copilot_actor(sandbox)}
    async with client_with_actors(e2e_session_factory, actors) as client:
        headers = auth(sandbox, idempotency_key=f"f6-concurrent-extend-{uuid4().hex}")
        path = "/v1/operational-copilot/tools/assignments/day-extensions"
        first, second = await asyncio.gather(
            client.post(path, json=body, headers=headers),
            client.post(path, json=body, headers=headers),
        )
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["result_id"] == second.json()["result_id"]
    assert assignment_recovery_exception_count(e2e_admin_conn, sandbox, supply.assignment_id) == 1
    _, after = owner_revisions(e2e_admin_conn, sandbox)
    assert after == availability_revision + 1
