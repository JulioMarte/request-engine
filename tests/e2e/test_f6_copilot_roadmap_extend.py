from typing import cast

import pytest

from request_engine.platform.db.session import SessionFactory

from .f4_capacity_support import seed_today_schedule
from .f5_booking_fixture import five_minute_sandbox
from .f5_contextual_support import contextualize_recovery_supply
from .f5_extend_day_fixture import (
    grant_extend_day_authority,
    recurring_schedule_snapshot,
)
from .f5_extend_day_support import assignment_recovery_exception_count
from .f6_copilot_support import copilot_actor, execute
from .f6_roadmap_support import seed_location_operational_hours
from .operational_support import PgConnection
from .tenant_sandbox import client_with_actors, seed_tenant_sandbox

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.e2e,
    pytest.mark.postgres,
    pytest.mark.contract,
    pytest.mark.invariant,
]


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
    sign = "-" if offset > 0 else "+"
    return f"Etc/GMT{sign}{abs(offset)}"


async def test_f6_executes_roadmap_named_resource_extend_today_without_recovery(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    base = seed_tenant_sandbox(e2e_admin_conn, "f6-roadmap-natural-extend")
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
    actors = {sandbox.token: copilot_actor(sandbox)}
    recurring_before = recurring_schedule_snapshot(e2e_admin_conn, sandbox, supply.assignment_id)
    assignment_before = assignment_recovery_exception_count(
        e2e_admin_conn, sandbox, supply.assignment_id
    )

    async with client_with_actors(e2e_session_factory, actors) as client:
        key = "f6-roadmap-dr-a-extend"
        executed = await execute(client, sandbox, "Dr. A will work until 7 PM today", key)
        replay = await execute(client, sandbox, "Dr. A will work until 7 PM today", key)

    incident = e2e_admin_conn.execute(
        "SELECT count(*) FROM request_engine.recovery_incidents WHERE organization_id=%s",
        (sandbox.organization_id,),
    ).fetchone()
    assert incident == (0,)
    assert executed["owner"] == "booking"
    assert executed["action"] == "extend_assignment_hours"
    assert executed["status"] == "applied"
    assert replay["result_id"] == executed["result_id"]
    assert (
        assignment_recovery_exception_count(e2e_admin_conn, sandbox, supply.assignment_id)
        == assignment_before + 1
    )
    assert (
        recurring_schedule_snapshot(e2e_admin_conn, sandbox, supply.assignment_id)
        == recurring_before
    )
