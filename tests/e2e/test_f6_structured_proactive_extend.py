from datetime import datetime, time, timedelta
from typing import cast
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from request_engine.platform.db.session import SessionFactory

from .f4_capacity_support import seed_today_schedule
from .f5_booking_fixture import five_minute_sandbox
from .f5_contextual_support import contextualize_recovery_supply
from .f5_extend_day_fixture import grant_extend_day_authority
from .f5_extend_day_support import assignment_recovery_exception_count
from .f6_copilot_support import copilot_actor, execute_tool, read_tool
from .f6_roadmap_support import seed_location_operational_hours
from .operational_support import PgConnection
from .tenant_sandbox import auth, client_with_actors, seed_tenant_sandbox
from .world_clock import world_weekday

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e, pytest.mark.postgres, pytest.mark.contract]


def _timezone_with_local_noon(conn: PgConnection) -> str:
    row = conn.execute(
        "SELECT EXTRACT(HOUR FROM clock_timestamp() AT TIME ZONE 'UTC')::int"
    ).fetchone()
    assert row is not None
    offset = 12 - cast(int, row[0])
    if offset > 12:
        offset -= 24
    if offset < -12:
        offset += 24
    if offset == 0:
        return "UTC"
    return f"Etc/GMT{'-' if offset > 0 else '+'}{abs(offset)}"


async def test_f6_structured_proactive_extend_without_recovery(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    base = seed_tenant_sandbox(e2e_admin_conn, "f6-structured-proactive-extend")
    sandbox = five_minute_sandbox(e2e_admin_conn, base)
    e2e_admin_conn.execute(
        "UPDATE request_engine.resources SET display_name='Dr. A' "
        "WHERE organization_id=%s AND id=%s",
        (sandbox.organization_id, sandbox.resource_id),
    )
    grant_extend_day_authority(e2e_admin_conn, sandbox)
    seed_today_schedule(
        e2e_admin_conn,
        sandbox,
        business_timezone=_timezone_with_local_noon(e2e_admin_conn),
    )
    seed_location_operational_hours(e2e_admin_conn, sandbox)
    supply = contextualize_recovery_supply(e2e_admin_conn, sandbox)
    e2e_admin_conn.execute(
        "UPDATE request_engine.resource_location_availability SET local_end='17:00' "
        "WHERE organization_id=%s AND resource_location_assignment_id=%s AND weekday=%s",
        (
            sandbox.organization_id,
            supply.assignment_id,
            world_weekday(e2e_admin_conn, sandbox),
        ),
    )
    actors = {sandbox.token: copilot_actor(sandbox)}

    async with client_with_actors(e2e_session_factory, actors) as client:
        resources = await read_tool(client, sandbox, "/resources?reference=Dr.%20A")
        resource = resources[0]
        clock = await read_tool(client, sandbox, f"/locations/{resource['location_id']}/clock")
        zone = ZoneInfo(clock["timezone"])
        observed = datetime.fromisoformat(clock["observed_at"]).astimezone(zone)
        day_end = await read_tool(
            client,
            sandbox,
            f"/assignments/{resource['assignment_id']}/day-end?weekday={observed.weekday()}",
        )
        start_at = datetime.combine(
            observed.date(), time.fromisoformat(day_end["day_end"]), tzinfo=zone
        )
        end_at = datetime.combine(observed.date(), time(19), tzinfo=zone)
        body = {
            "assignment_id": resource["assignment_id"],
            "start_at": start_at.isoformat(),
            "end_at": end_at.isoformat(),
            "expected_resource_availability_revision": resource["resource_availability_revision"],
            "reason": "operator extended today",
        }
        before = assignment_recovery_exception_count(e2e_admin_conn, sandbox, supply.assignment_id)
        key = f"f6-proactive-extend-{uuid4().hex}"
        executed = await execute_tool(client, sandbox, "/assignments/day-extensions", body, key)
        replay = await execute_tool(client, sandbox, "/assignments/day-extensions", body, key)
        assert executed["owner"] == "booking"
        assert executed["action"] == "extend_assignment_hours"
        assert executed["status"] == "applied"
        assert replay["result_id"] == executed["result_id"]

        stale = await client.post(
            "/v1/operational-copilot/tools/assignments/day-extensions",
            json=body,
            headers=auth(sandbox, idempotency_key=f"{key}:stale"),
        )
        assert stale.status_code == 409, stale.text

        conflicting = await client.post(
            "/v1/operational-copilot/tools/assignments/day-extensions",
            json={**body, "end_at": (end_at + timedelta(hours=1)).isoformat()},
            headers=auth(sandbox, idempotency_key=key),
        )
        assert conflicting.status_code == 409, conflicting.text

    surviving = e2e_admin_conn.execute(
        "SELECT count(*), max(upper(during)) "
        "FROM request_engine.resource_location_schedule_exceptions "
        "WHERE organization_id=%s AND resource_location_assignment_id=%s AND active",
        (sandbox.organization_id, supply.assignment_id),
    ).fetchone()
    assert surviving is not None
    assert surviving[0] == before + 1
    assert surviving[1] == end_at
    assert (
        assignment_recovery_exception_count(e2e_admin_conn, sandbox, supply.assignment_id)
        == before + 1
    )
    incident = e2e_admin_conn.execute(
        "SELECT count(*) FROM request_engine.operational_recovery_incidents "
        "WHERE organization_id=%s",
        (sandbox.organization_id,),
    ).fetchone()
    assert incident == (0,)
