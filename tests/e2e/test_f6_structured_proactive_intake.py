from uuid import uuid4

import pytest

from request_engine.platform.db.session import SessionFactory

from .f5_booking_fixture import five_minute_sandbox
from .f6_copilot_support import copilot_actor, execute_tool, read_tool
from .operational_support import PgConnection
from .tenant_sandbox import auth, client_with_actors, seed_tenant_sandbox

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e, pytest.mark.postgres, pytest.mark.contract]


async def test_f6_structured_proactive_intake_without_recovery(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    base = seed_tenant_sandbox(e2e_admin_conn, "f6-structured-proactive-intake")
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
        key = f"f6-proactive-intake-{uuid4().hex}"
        executed = await execute_tool(client, sandbox, "/queues/intake-control", body, key)
        replay = await execute_tool(client, sandbox, "/queues/intake-control", body, key)

        assert executed["owner"] == "queue"
        assert executed["action"] == "set_intake_control"
        assert executed["status"] == "applied"
        assert replay["result_id"] == executed["result_id"]

        current = await read_tool(client, sandbox, f"/queues/{sandbox.queue_id}/intake")
        assert current["accepting"] is False
        assert current["revision"] == intake["revision"] + 1

        stale = await client.post(
            "/v1/operational-copilot/tools/queues/intake-control",
            json=body,
            headers=auth(sandbox, idempotency_key=f"{key}:stale"),
        )
        assert stale.status_code == 409, stale.text

    incident = e2e_admin_conn.execute(
        "SELECT count(*) FROM request_engine.operational_recovery_incidents "
        "WHERE organization_id=%s",
        (sandbox.organization_id,),
    ).fetchone()
    assert incident == (0,)
