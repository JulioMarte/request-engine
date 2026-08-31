from uuid import uuid4

import pytest

from request_engine.platform.db.session import SessionFactory

from .f4_capacity_support import seed_today_schedule
from .f4_operational_day_support import configure_projection
from .f5_booking_fixture import five_minute_sandbox
from .f5_recovery_support import book_commitments, restrict_source_to_first_six
from .f6_copilot_support import copilot_actor, execute_tool, read_tool
from .operational_support import PgConnection
from .tenant_sandbox import auth, client_with_actors, seed_tenant_sandbox

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e, pytest.mark.postgres, pytest.mark.contract]


async def test_f6_structured_recovery_replay_and_conflicting_replay(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    base = seed_tenant_sandbox(e2e_admin_conn, "f6-structured-recovery")
    sandbox = five_minute_sandbox(e2e_admin_conn, base)
    seed_today_schedule(e2e_admin_conn, sandbox)
    actors = {sandbox.token: copilot_actor(sandbox)}
    async with client_with_actors(e2e_session_factory, actors) as client:
        await configure_projection(client, sandbox)
        _, slots = await book_commitments(client, e2e_admin_conn, sandbox)
        restrict_source_to_first_six(e2e_admin_conn, sandbox, slots)

        at_risk = await read_tool(
            client,
            sandbox,
            f"/queues/{sandbox.queue_id}/at-risk-reservations",
        )
        reservation_id = at_risk["affected"][0]["reservation_id"]
        proposal_key = f"f6-structured-proposal-{uuid4().hex}"
        proposal_body = {"service_queue_id": str(sandbox.queue_id), "search_days": 7}
        proposal = await execute_tool(
            client, sandbox, "/recovery/proposals", proposal_body, proposal_key
        )
        proposal_replay = await execute_tool(
            client, sandbox, "/recovery/proposals", proposal_body, proposal_key
        )
        assert proposal["action"] == "create_proposal"
        assert proposal_replay["result_id"] == proposal["result_id"]
        proposal_conflict = await client.post(
            "/v1/operational-copilot/tools/recovery/proposals",
            json={**proposal_body, "search_days": 8},
            headers=auth(sandbox, idempotency_key=proposal_key),
        )
        assert proposal_conflict.status_code == 409, proposal_conflict.text

        execute_key = f"f6-structured-execution-{uuid4().hex}"
        execution_body = {
            "proposal_id": proposal["result_id"],
            "reservation_id": reservation_id,
            "notify": True,
        }
        executed = await execute_tool(
            client, sandbox, "/recovery/executions", execution_body, execute_key
        )
        replay = await execute_tool(
            client, sandbox, "/recovery/executions", execution_body, execute_key
        )
        assert executed["action"] == "execute_recovery"
        assert executed["status"] == "succeeded"
        assert replay["result_id"] == executed["result_id"]
        execute_conflict = await client.post(
            "/v1/operational-copilot/tools/recovery/executions",
            json={**execution_body, "notify": False},
            headers=auth(sandbox, idempotency_key=execute_key),
        )
        assert execute_conflict.status_code == 409, execute_conflict.text

        row = e2e_admin_conn.execute(
            """
            SELECT count(*) FROM request_engine.operational_recovery_actions
            WHERE organization_id=%s AND id=%s
            """,
            (sandbox.organization_id, executed["result_id"]),
        ).fetchone()
        assert row is not None and row[0] == 1
