from uuid import uuid4

import pytest

from request_engine.platform.db.session import SessionFactory

from .f4_capacity_support import seed_today_schedule
from .f4_operational_day_support import configure_projection
from .f5_booking_fixture import five_minute_sandbox
from .f5_recovery_assertions import create_proposal
from .f5_recovery_support import book_commitments, restrict_source_to_first_six
from .f5_replace_resource_support import seed_incident_for_proposal
from .f6_copilot_support import copilot_actor, execute_tool, read_tool
from .operational_support import PgConnection
from .tenant_sandbox import client_with_actors, seed_tenant_sandbox

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e, pytest.mark.postgres, pytest.mark.contract]


async def test_f6_structured_intake_stop_reopen_and_replay(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    base = seed_tenant_sandbox(e2e_admin_conn, "f6-structured-intake")
    sandbox = five_minute_sandbox(e2e_admin_conn, base)
    seed_today_schedule(e2e_admin_conn, sandbox)
    actors = {sandbox.token: copilot_actor(sandbox)}
    async with client_with_actors(e2e_session_factory, actors) as client:
        await configure_projection(client, sandbox)
        _, slots = await book_commitments(client, e2e_admin_conn, sandbox)
        restrict_source_to_first_six(e2e_admin_conn, sandbox, slots)
        proposal = await create_proposal(client, sandbox)
        incident_id = seed_incident_for_proposal(e2e_admin_conn, sandbox, proposal)

        incident = await read_tool(
            client,
            sandbox,
            f"/queues/{sandbox.queue_id}/recovery-incident",
        )
        intake = await read_tool(client, sandbox, f"/queues/{sandbox.queue_id}/intake")
        assert incident["incident_id"] == str(incident_id)
        assert intake["accepting"] is True

        stop_body = {
            "incident_id": str(incident_id),
            "accepting": False,
            "expected_source_revision": incident["source_revision"],
            "expected_intake_revision": intake["revision"],
            "reason": "structured F6 stop",
        }
        stop_key = f"f6-structured-stop-{uuid4().hex}"
        stopped = await execute_tool(client, sandbox, "/recovery/intake", stop_body, stop_key)
        stop_replay = await execute_tool(client, sandbox, "/recovery/intake", stop_body, stop_key)
        assert stop_replay["result_id"] == stopped["result_id"]

        incident = await read_tool(
            client,
            sandbox,
            f"/queues/{sandbox.queue_id}/recovery-incident",
        )
        intake = await read_tool(client, sandbox, f"/queues/{sandbox.queue_id}/intake")
        assert intake["accepting"] is False
        reopen_body = {
            "incident_id": str(incident_id),
            "accepting": True,
            "expected_source_revision": incident["source_revision"],
            "expected_intake_revision": intake["revision"],
            "reason": "structured F6 reopen",
        }
        reopen_key = f"f6-structured-reopen-{uuid4().hex}"
        reopened = await execute_tool(client, sandbox, "/recovery/intake", reopen_body, reopen_key)
        replay = await execute_tool(client, sandbox, "/recovery/intake", reopen_body, reopen_key)
        assert reopened["action"] == "reopen_intake"
        assert replay["result_id"] == reopened["result_id"]
        final_state = await read_tool(client, sandbox, f"/queues/{sandbox.queue_id}/intake")
        assert final_state["accepting"] is True
