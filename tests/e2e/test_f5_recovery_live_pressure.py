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


async def _add_walk_in(client, conn, sandbox, world) -> None:
    response = await client.post(
        f"/v1/queues/{sandbox.queue_id}/check-in",
        json={
            "subject_party_id": str(seed_walk_in_subject(conn, sandbox)),
            "expected_workload_classification_id": str(world.walk_in_workload_id),
        },
        headers=auth(sandbox, idempotency_key=f"f5-live-pressure-{uuid4().hex}"),
    )
    assert response.status_code == 201, response.text


async def test_f5_live_pressure_changes_risk_without_fabricating_more_affected_reservations(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = seed_tenant_sandbox(e2e_admin_conn, "f5-live-pressure")
    actors = {sandbox.token: f5_actor(sandbox)}
    async with client_with_actors(e2e_session_factory, actors) as client:
        world = await prepare_recovery_world(client, e2e_admin_conn, sandbox)
        structural = await create_proposal(client, sandbox)
        expected_affected = world.reservations[6:]
        assert (
            tuple(UUID(item["reservation_id"]) for item in structural["affected"])
            == expected_affected
        )

        await _add_walk_in(client, e2e_admin_conn, sandbox, world)
        pressured = await create_proposal(client, sandbox)

    assert pressured["committed_capacity_seconds"] == 3000
    assert pressured["executable_capacity_seconds"] == 1800
    assert pressured["shortfall_seconds"] == 2400
    assert pressured["source_fingerprint"] != structural["source_fingerprint"]
    assert (
        tuple(UUID(item["reservation_id"]) for item in pressured["affected"])
        == expected_affected
    )


async def test_f5_live_only_pressure_persists_risk_only_proposal_with_no_affected_reservations(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = seed_tenant_sandbox(e2e_admin_conn, "f5-live-only-pressure")
    actors = {sandbox.token: f5_actor(sandbox)}
    async with client_with_actors(e2e_session_factory, actors) as client:
        world = await prepare_recovery_world(
            client,
            e2e_admin_conn,
            sandbox,
            capacity_slots=10,
        )
        await _add_walk_in(client, e2e_admin_conn, sandbox, world)
        proposal = await create_proposal(client, sandbox)

    assert proposal["committed_capacity_seconds"] == 3000
    assert proposal["executable_capacity_seconds"] == 3000
    assert proposal["shortfall_seconds"] > 0
    assert proposal["affected"] == []
