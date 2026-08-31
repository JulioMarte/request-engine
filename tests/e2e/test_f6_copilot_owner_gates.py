from uuid import uuid4

import pytest

from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext

from .f6_copilot_support import copilot_actor
from .operational_support import PgConnection
from .tenant_sandbox import auth, client_with_actors, seed_tenant_sandbox

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.e2e,
    pytest.mark.postgres,
    pytest.mark.contract,
    pytest.mark.adversarial,
]


async def test_f6_execute_requires_the_registered_owner_capability(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = seed_tenant_sandbox(e2e_admin_conn, "f6-copilot-owner-capability")
    full_actor = copilot_actor(sandbox)
    actor = ActorContext(
        full_actor.organization_id,
        full_actor.principal_id,
        full_actor.capabilities - {"operational_recovery.execute"},
    )
    actors = {sandbox.token: actor}
    key = f"f6-owner-gate-{uuid4().hex}"
    incident_id = uuid4()
    text = (
        f"stop walk-ins for incident {incident_id} "
        "source revision 1 intake revision 1"
    )

    async with client_with_actors(e2e_session_factory, actors) as client:
        response = await client.post(
            "/v1/operational-copilot/execute",
            json={"text": text},
            headers=auth(sandbox, idempotency_key=key),
        )

    assert response.status_code == 403, response.text
    count = e2e_admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.operational_recovery_actions
        WHERE organization_id=%s AND principal_id=%s AND idempotency_key=%s
        """,
        (sandbox.organization_id, sandbox.principal_id, key),
    ).fetchone()
    assert count is not None
    assert count[0] == 0
