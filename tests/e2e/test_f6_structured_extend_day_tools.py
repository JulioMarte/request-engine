from datetime import datetime, time
from typing import cast
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from request_engine.platform.db.session import SessionFactory

from .f4_capacity_support import seed_today_schedule
from .f4_operational_day_support import configure_projection
from .f5_booking_fixture import five_minute_sandbox
from .f5_contextual_support import contextualize_recovery_supply, restrict_contextual_capacity
from .f5_extend_day_fixture import close_location_after_slots, grant_extend_day_authority
from .f5_extend_day_support import assignment_recovery_exception_count
from .f5_recovery_assertions import create_proposal
from .f5_recovery_support import book_commitments
from .f5_replace_resource_support import seed_incident_for_proposal
from .f6_copilot_support import copilot_actor, execute_tool, read_tool
from .operational_support import PgConnection
from .tenant_sandbox import auth, client_with_actors, seed_tenant_sandbox

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


async def test_f6_structured_extend_day_replay_and_conflict(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    base = seed_tenant_sandbox(e2e_admin_conn, "f6-structured-extend-day")
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
    supply = contextualize_recovery_supply(e2e_admin_conn, sandbox)
    actors = {sandbox.token: copilot_actor(sandbox)}
    async with client_with_actors(e2e_session_factory, actors) as client:
        await configure_projection(client, sandbox)
        _, slots = await book_commitments(client, e2e_admin_conn, sandbox)
        restrict_contextual_capacity(e2e_admin_conn, sandbox, supply, slots, count=6)
        close_location_after_slots(e2e_admin_conn, sandbox, slots, count=6)
        proposal = await create_proposal(client, sandbox)
        seed_incident_for_proposal(e2e_admin_conn, sandbox, proposal)

        resources = await read_tool(client, sandbox, "/resources?reference=Dr.%20A")
        assert len(resources) == 1 and resources[0]["display_name"] == "Dr. A"
        resource = resources[0]
        clock = await read_tool(
            client, sandbox, f"/locations/{resource['location_id']}/clock"
        )
        zone = ZoneInfo(clock["timezone"])
        observed = datetime.fromisoformat(clock["observed_at"]).astimezone(zone)
        day_end = await read_tool(
            client,
            sandbox,
            f"/assignments/{resource['assignment_id']}/day-end?weekday={observed.weekday()}",
        )
        incident = await read_tool(
            client, sandbox, f"/queues/{sandbox.queue_id}/recovery-incident"
        )
        start_at = datetime.combine(
            observed.date(),
            time.fromisoformat(day_end["day_end"]),
            tzinfo=zone,
        )
        end_at = datetime.combine(observed.date(), time(19), tzinfo=zone)
        body = {
            "incident_id": incident["incident_id"],
            "assignment_id": resource["assignment_id"],
            "start_at": start_at.isoformat(),
            "end_at": end_at.isoformat(),
            "expected_source_revision": incident["source_revision"],
            "expected_location_operational_revision": clock["operational_revision"],
            "expected_resource_availability_revision": resource[
                "resource_availability_revision"
            ],
            "reason": "structured F6 extend day",
        }
        key = f"f6-structured-extend-{uuid4().hex}"
        before = assignment_recovery_exception_count(
            e2e_admin_conn, sandbox, supply.assignment_id
        )
        executed = await execute_tool(
            client, sandbox, "/recovery/day-extensions", body, key
        )
        replay = await execute_tool(
            client, sandbox, "/recovery/day-extensions", body, key
        )
        assert executed["action"] == "extend_day"
        assert replay["result_id"] == executed["result_id"]
        conflict = await client.post(
            "/v1/operational-copilot/tools/recovery/day-extensions",
            json={**body, "reason": "different extension payload"},
            headers=auth(sandbox, idempotency_key=key),
        )
        assert conflict.status_code == 409, conflict.text

    assert assignment_recovery_exception_count(
        e2e_admin_conn, sandbox, supply.assignment_id
    ) == before + 1
