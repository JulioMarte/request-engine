from datetime import datetime, time
from typing import cast
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from request_engine.platform.db.session import SessionFactory

from .f5_booking_fixture import five_minute_sandbox
from .f5_contextual_support import contextualize_recovery_supply
from .f5_extend_day_fixture import grant_extend_day_authority
from .f5_extend_day_support import assignment_recovery_exception_count
from .f6_copilot_support import copilot_actor, execute_tool, read_tool
from .f6_roadmap_support import seed_named_resource_day_schedule
from .operational_support import PgConnection
from .tenant_sandbox import (
    TenantSandbox,
    client_with_actors,
    seed_tenant_sandbox,
)
from .world_clock import world_weekday

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e, pytest.mark.postgres, pytest.mark.contract]


async def test_roadmap_extend_day_satisfied_by_structured_tools(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    base = seed_tenant_sandbox(e2e_admin_conn, "f6-scenario-extend")
    sandbox = five_minute_sandbox(e2e_admin_conn, base)
    grant_extend_day_authority(e2e_admin_conn, sandbox)
    seed_named_resource_day_schedule(e2e_admin_conn, sandbox, display_name="Dr. A")
    supply = contextualize_recovery_supply(e2e_admin_conn, sandbox)
    e2e_admin_conn.execute(
        "UPDATE request_engine.resource_location_availability SET local_end='17:00' "
        "WHERE organization_id=%s AND resource_location_assignment_id=%s AND weekday=%s",
        (sandbox.organization_id, supply.assignment_id, world_weekday(e2e_admin_conn, sandbox)),
    )
    actors = {sandbox.token: copilot_actor(sandbox)}
    async with client_with_actors(e2e_session_factory, actors) as client:
        resource = (await read_tool(client, sandbox, "/resources?reference=Dr.%20A"))[0]
        clock = await read_tool(client, sandbox, f"/locations/{resource['location_id']}/clock")
        zone = ZoneInfo(clock["timezone"])
        observed = datetime.fromisoformat(clock["observed_at"]).astimezone(zone)
        day_end = await read_tool(
            client,
            sandbox,
            f"/assignments/{resource['assignment_id']}/day-end?weekday={observed.weekday()}",
        )
        body = {
            "assignment_id": str(resource["assignment_id"]),
            "start_at": datetime.combine(
                observed.date(), time.fromisoformat(day_end["day_end"]), tzinfo=zone
            ).isoformat(),
            "end_at": datetime.combine(observed.date(), time(19), tzinfo=zone).isoformat(),
            "expected_resource_availability_revision": resource["resource_availability_revision"],
            "reason": "Dr. A will work until 7 PM today",
        }
        key = f"f6-scenario-extend-{uuid4().hex}"
        receipt = await execute_tool(client, sandbox, "/assignments/day-extensions", body, key)
    assert receipt["owner"] == "booking" and receipt["action"] == "extend_assignment_hours"
    assert assignment_recovery_exception_count(e2e_admin_conn, sandbox, supply.assignment_id) == 1
    assert _incident_count(e2e_admin_conn, sandbox) == 0


async def test_roadmap_stop_walk_ins_satisfied_by_structured_tools(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    base = seed_tenant_sandbox(e2e_admin_conn, "f6-scenario-intake")
    sandbox = five_minute_sandbox(e2e_admin_conn, base)
    actors = {sandbox.token: copilot_actor(sandbox)}
    async with client_with_actors(e2e_session_factory, actors) as client:
        queue = (await read_tool(client, sandbox, "/queues"))[0]
        intake = await read_tool(client, sandbox, f"/queues/{queue['service_queue_id']}/intake")
        clock = await read_tool(client, sandbox, f"/locations/{queue['location_id']}/clock")
        body = {
            "service_queue_id": str(queue["service_queue_id"]),
            "accepting": False,
            "expected_intake_revision": intake["revision"],
            "reason": "stop accepting walk-ins for the rest of the day",
            "effective_until": clock["operational_day_end_at"],
        }
        receipt = await execute_tool(
            client, sandbox, "/queues/intake-control", body, f"f6-scenario-intake-{uuid4().hex}"
        )
        current = await read_tool(client, sandbox, f"/queues/{queue['service_queue_id']}/intake")
        assert current["accepting"] is False
        assert current["revision"] == intake["revision"] + 1
    assert receipt["owner"] == "queue" and receipt["action"] == "set_intake_control"
    assert _incident_count(e2e_admin_conn, sandbox) == 0


def _incident_count(conn: PgConnection, sandbox: TenantSandbox) -> int:
    row = conn.execute(
        "SELECT count(*) FROM request_engine.operational_recovery_incidents "
        "WHERE organization_id=%s",
        (sandbox.organization_id,),
    ).fetchone()
    assert row is not None
    return cast(int, row[0])
