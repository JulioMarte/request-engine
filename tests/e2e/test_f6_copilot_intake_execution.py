from datetime import datetime
from typing import cast
from uuid import uuid4

import pytest

from request_engine.platform.db.session import SessionFactory

from .f3_acceptance_assertions import seed_walk_in_subject
from .f4_capacity_support import seed_today_schedule
from .f4_operational_day_support import configure_projection
from .f5_booking_fixture import five_minute_sandbox
from .f5_recovery_assertions import create_proposal
from .f5_recovery_support import book_commitments, restrict_source_to_first_six
from .f5_replace_resource_support import seed_incident_for_proposal
from .f6_copilot_support import copilot_actor, execute
from .f6_roadmap_support import seed_location_operational_hours
from .operational_support import PgConnection
from .tenant_sandbox import auth, client_with_actors, seed_tenant_sandbox

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.e2e,
    pytest.mark.postgres,
    pytest.mark.contract,
    pytest.mark.adversarial,
]


async def test_f6_execute_routes_intake_language_through_owner_service(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    base = seed_tenant_sandbox(e2e_admin_conn, "f6-copilot-execute-intake")
    sandbox = five_minute_sandbox(e2e_admin_conn, base)
    seed_today_schedule(e2e_admin_conn, sandbox)
    actors = {sandbox.token: copilot_actor(sandbox)}
    async with client_with_actors(e2e_session_factory, actors) as client:
        await configure_projection(client, sandbox)
        _, slots = await book_commitments(client, e2e_admin_conn, sandbox)
        restrict_source_to_first_six(e2e_admin_conn, sandbox, slots)
        proposal = await create_proposal(client, sandbox)
        incident_id = seed_incident_for_proposal(e2e_admin_conn, sandbox, proposal)
        source_revision = int(proposal["source_checkpoint"]["recovery_source_revision"])
        text = (
            f"stop walk-ins for incident {incident_id} "
            f"source revision {source_revision} intake revision 1"
        )
        key = f"f6-execute-intake-{uuid4().hex}"

        executed = await execute(client, sandbox, text, key)
        replay = await execute(client, sandbox, text, key)

        assert executed["owner"] == "operational_recovery"
        assert executed["action"] == "stop_intake"
        assert executed["status"] == "succeeded"
        assert executed["idempotency_key"] == key
        assert replay["result_id"] == executed["result_id"]

        subject = seed_walk_in_subject(e2e_admin_conn, sandbox)
        blocked = await client.post(
            f"/v1/queues/{sandbox.queue_id}/check-in",
            json={"subject_party_id": str(subject)},
            headers=auth(sandbox, idempotency_key=f"f6-blocked-{uuid4().hex}"),
        )
        assert blocked.status_code == 409, blocked.text


async def test_f6_execute_rest_of_day_without_recovery_incident(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    base = seed_tenant_sandbox(e2e_admin_conn, "f6-copilot-rest-of-day")
    sandbox = five_minute_sandbox(e2e_admin_conn, base)
    seed_today_schedule(e2e_admin_conn, sandbox)
    seed_location_operational_hours(e2e_admin_conn, sandbox)
    actors = {sandbox.token: copilot_actor(sandbox)}
    async with client_with_actors(e2e_session_factory, actors) as client:
        key = f"f6-rest-of-day-{uuid4().hex}"

        executed = await execute(
            client,
            sandbox,
            "stop accepting walk-ins for the rest of the day",
            key,
        )
        replay = await execute(
            client,
            sandbox,
            "stop accepting walk-ins for the rest of the day",
            key,
        )

        assert executed["owner"] == "queue"
        assert executed["action"] == "set_intake_control"
        assert executed["status"] == "applied"
        assert replay["result_id"] == executed["result_id"]

        row = e2e_admin_conn.execute(
            """
            SELECT accepting, reason, effective_until, clock_timestamp()
            FROM request_engine.service_queue_intake_controls
            WHERE organization_id=%s AND service_queue_id=%s
            """,
            (sandbox.organization_id, sandbox.queue_id),
        ).fetchone()
        assert row is not None
        assert row[0] is False
        assert row[1] == "operational copilot: stop accepting walk-ins for the rest of the day"
        effective_until = cast(datetime, row[2])
        observed_at = cast(datetime, row[3])
        assert effective_until > observed_at

        incident = e2e_admin_conn.execute(
            "SELECT count(*) FROM request_engine.operational_recovery_incidents "
            "WHERE organization_id=%s",
            (sandbox.organization_id,),
        ).fetchone()
        assert incident == (0,)

        subject = seed_walk_in_subject(e2e_admin_conn, sandbox)
        blocked = await client.post(
            f"/v1/queues/{sandbox.queue_id}/check-in",
            json={"subject_party_id": str(subject)},
            headers=auth(sandbox, idempotency_key=f"f6-rest-blocked-{uuid4().hex}"),
        )
        assert blocked.status_code == 409, blocked.text
