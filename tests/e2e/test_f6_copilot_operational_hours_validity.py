from datetime import date, time, timedelta
from typing import cast

import pytest

from request_engine.platform.db.session import SessionFactory

from .f4_capacity_support import seed_today_schedule
from .f4_operational_day_support import configure_projection
from .f5_booking_fixture import five_minute_sandbox
from .f5_recovery_assertions import create_proposal
from .f5_recovery_support import book_commitments, restrict_source_to_first_six
from .f5_replace_resource_support import seed_incident_for_proposal
from .f6_copilot_support import copilot_actor, execute
from .f6_roadmap_support import seed_location_operational_hours
from .operational_support import PgConnection
from .tenant_sandbox import client_with_actors, seed_tenant_sandbox
from .world_clock import location_timezone, world_weekday

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.e2e,
    pytest.mark.postgres,
    pytest.mark.contract,
    pytest.mark.adversarial,
]


async def test_rest_of_day_ignores_inactive_expired_and_future_hours(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    base = seed_tenant_sandbox(e2e_admin_conn, "f6-operational-hours-validity")
    sandbox = five_minute_sandbox(e2e_admin_conn, base)
    seed_today_schedule(e2e_admin_conn, sandbox)
    timezone = location_timezone(e2e_admin_conn, sandbox)
    row = e2e_admin_conn.execute(
        "SELECT (clock_timestamp() AT TIME ZONE %s)::date",
        (timezone.key,),
    ).fetchone()
    assert row is not None
    local_date = cast(date, row[0])

    e2e_admin_conn.execute(
        "DELETE FROM request_engine.location_operational_hours "
        "WHERE organization_id=%s AND location_id=%s AND weekday=%s",
        (sandbox.organization_id, sandbox.location_id, world_weekday(e2e_admin_conn, sandbox)),
    )
    seed_location_operational_hours(
        e2e_admin_conn,
        sandbox,
        local_end=time(22, 0),
        valid_from=local_date,
        valid_until=local_date,
    )
    seed_location_operational_hours(
        e2e_admin_conn,
        sandbox,
        local_end=time(23, 15),
        active=False,
    )
    seed_location_operational_hours(
        e2e_admin_conn,
        sandbox,
        local_end=time(23, 30),
        valid_until=local_date - timedelta(days=1),
    )
    seed_location_operational_hours(
        e2e_admin_conn,
        sandbox,
        local_end=time(23, 45),
        valid_from=local_date + timedelta(days=1),
    )

    actors = {sandbox.token: copilot_actor(sandbox)}
    async with client_with_actors(e2e_session_factory, actors) as client:
        await configure_projection(client, sandbox)
        _, slots = await book_commitments(client, e2e_admin_conn, sandbox)
        restrict_source_to_first_six(e2e_admin_conn, sandbox, slots)
        proposal = await create_proposal(client, sandbox)
        seed_incident_for_proposal(e2e_admin_conn, sandbox, proposal)

        executed = await execute(
            client,
            sandbox,
            "stop accepting walk-ins for the rest of the day",
            "f6-operational-hours-validity",
        )

    assert executed["action"] == "set_intake_control"
    row = e2e_admin_conn.execute(
        """
        SELECT effective_until
        FROM request_engine.service_queue_intake_controls
        WHERE organization_id=%s AND service_queue_id=%s
        """,
        (sandbox.organization_id, sandbox.queue_id),
    ).fetchone()
    assert row is not None
    effective_until = row[0]
    assert effective_until.astimezone(timezone).time().replace(tzinfo=None) == time(22, 0)
