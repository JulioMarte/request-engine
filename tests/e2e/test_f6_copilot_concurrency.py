import asyncio
from uuid import uuid4

import pytest

from request_engine.platform.db.session import SessionFactory

from .f4_capacity_support import seed_today_schedule
from .f4_operational_day_support import configure_projection
from .f5_booking_fixture import five_minute_sandbox
from .f5_recovery_assertions import create_proposal
from .f5_recovery_support import book_commitments, restrict_source_to_first_six
from .f5_replace_resource_support import seed_incident_for_proposal
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


async def test_f6_concurrent_natural_replay_creates_one_owner_action(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    base = seed_tenant_sandbox(e2e_admin_conn, "f6-concurrent-natural-replay")
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
        key = f"f6-concurrent-{uuid4().hex}"
        headers = auth(sandbox, idempotency_key=key)

        first, second = await asyncio.gather(
            client.post(
                "/v1/operational-copilot/execute",
                json={"text": text},
                headers=headers,
            ),
            client.post(
                "/v1/operational-copilot/execute",
                json={"text": text},
                headers=headers,
            ),
        )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["result_id"] == second.json()["result_id"]
    row = e2e_admin_conn.execute(
        """
        SELECT count(*) FROM request_engine.operational_recovery_actions
        WHERE organization_id=%s AND principal_id=%s AND idempotency_key=%s
        """,
        (sandbox.organization_id, sandbox.principal_id, key),
    ).fetchone()
    assert row is not None and row[0] == 1
