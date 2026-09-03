from datetime import datetime
from uuid import uuid4

import pytest

from request_engine.platform.db.session import SessionFactory

from .f5_booking_fixture import five_minute_sandbox
from .f6_copilot_support import copilot_actor, read_tool
from .operational_support import PgConnection
from .tenant_sandbox import auth, client_with_actors, seed_tenant_sandbox

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.e2e,
    pytest.mark.postgres,
    pytest.mark.contract,
    pytest.mark.adversarial,
]


@pytest.mark.parametrize(
    ("override", "label"),
    (
        ({"expected_intake_revision": 0}, "zero-revision"),
        ({"reason": "   "}, "blank-reason"),
        ({"effective_until": datetime(2030, 1, 1, 18, 0).isoformat()}, "naive-until"),
    ),
)
async def test_f6_operational_intake_rejects_owner_invalid_input_at_http_boundary(
    override: dict[str, object],
    label: str,
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = five_minute_sandbox(
        e2e_admin_conn, seed_tenant_sandbox(e2e_admin_conn, f"f6-invalid-{label}")
    )
    key = f"f6-invalid-{label}-{uuid4().hex}"
    actors = {sandbox.token: copilot_actor(sandbox)}
    async with client_with_actors(e2e_session_factory, actors) as client:
        state = await read_tool(client, sandbox, f"/queues/{sandbox.queue_id}/intake")
        body: dict[str, object] = {
            "service_queue_id": str(sandbox.queue_id),
            "accepting": False,
            "expected_intake_revision": state["revision"],
            "reason": "adversarial validation",
        }
        body.update(override)
        response = await client.post(
            "/v1/operational-copilot/tools/queues/intake-control",
            json=body,
            headers=auth(sandbox, idempotency_key=key),
        )
    assert response.status_code == 422, response.text
    row = e2e_admin_conn.execute(
        "SELECT count(*) FROM request_engine.idempotency_records "
        "WHERE organization_id=%s AND idempotency_key=%s",
        (sandbox.organization_id, key),
    ).fetchone()
    assert row == (0,)
