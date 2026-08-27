from uuid import UUID, uuid4

import pytest

from request_engine.platform.db.session import SessionFactory

from .f3_acceptance_assertions import seed_walk_in_subject
from .f5_recovery_assertions import create_proposal
from .f5_recovery_support import f5_actor
from .f5_recovery_world import prepare_recovery_world
from .operational_support import PgConnection
from .tenant_sandbox import auth, client_with_actors, seed_tenant_sandbox

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.e2e,
    pytest.mark.postgres,
    pytest.mark.invariant,
    pytest.mark.contract,
    pytest.mark.adversarial,
    pytest.mark.capacity,
    pytest.mark.provenance,
]


async def test_f5_live_walk_in_pressure_expands_shortfall_and_affected_set(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = seed_tenant_sandbox(e2e_admin_conn, "f5-live-pressure")
    actors = {sandbox.token: f5_actor(sandbox)}
    async with client_with_actors(e2e_session_factory, actors) as client:
        world = await prepare_recovery_world(client, e2e_admin_conn, sandbox)
        structural = await create_proposal(client, sandbox)
        assert structural["shortfall_seconds"] == 1200
        assert tuple(UUID(item["reservation_id"]) for item in structural["affected"]) == (
            world.reservations[6:]
        )

        walk_in = await client.post(
            f"/v1/queues/{sandbox.queue_id}/check-in",
            json={
                "subject_party_id": str(seed_walk_in_subject(e2e_admin_conn, sandbox)),
                "expected_workload_classification_id": str(world.walk_in_workload_id),
            },
            headers=auth(sandbox, idempotency_key=f"f5-live-pressure-{uuid4().hex}"),
        )
        assert walk_in.status_code == 201, walk_in.text
        pressured = await create_proposal(client, sandbox)

    assert pressured["committed_capacity_seconds"] == 3000
    assert pressured["executable_capacity_seconds"] == 1800
    assert pressured["shortfall_seconds"] == 2400
    assert pressured["source_fingerprint"] != structural["source_fingerprint"]
    assert tuple(UUID(item["reservation_id"]) for item in pressured["affected"]) == (
        world.reservations[2:]
    )
