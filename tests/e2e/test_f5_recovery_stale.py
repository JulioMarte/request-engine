from uuid import UUID, uuid4

import pytest

from request_engine.platform.db.session import SessionFactory

from .f3_acceptance_assertions import seed_walk_in_subject
from .f5_recovery_assertions import (
    create_proposal,
    execute_proposal,
    execution_row,
    recovery_counts,
    reservation_state,
)
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
    pytest.mark.temporal,
]


async def test_f5_live_truth_change_rejects_stale_proposal_without_booking_or_notification(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = seed_tenant_sandbox(e2e_admin_conn, "f5-stale")
    actors = {sandbox.token: f5_actor(sandbox)}
    async with client_with_actors(e2e_session_factory, actors) as client:
        world = await prepare_recovery_world(client, e2e_admin_conn, sandbox)
        proposal = await create_proposal(client, sandbox)
        affected_id = UUID(proposal["affected"][0]["reservation_id"])
        before_reservation = reservation_state(e2e_admin_conn, affected_id)
        walk_in = await client.post(
            f"/v1/queues/{sandbox.queue_id}/check-in",
            json={
                "subject_party_id": str(seed_walk_in_subject(e2e_admin_conn, sandbox)),
                "expected_workload_classification_id": str(world.walk_in_workload_id),
            },
            headers=auth(sandbox, idempotency_key=f"f5-stale-walkin-{uuid4().hex}"),
        )
        assert walk_in.status_code == 201, walk_in.text
        before_effects = recovery_counts(e2e_admin_conn, sandbox.organization_id)
        response = await execute_proposal(
            client,
            sandbox,
            proposal,
            affected_id,
            idempotency_key=f"f5-stale-execute-{uuid4().hex}",
        )

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "STALE_RECOVERY_PROPOSAL"
    assert reservation_state(e2e_admin_conn, affected_id) == before_reservation
    after_effects = recovery_counts(e2e_admin_conn, sandbox.organization_id)
    assert after_effects[0] == before_effects[0] + 1
    assert after_effects[1:] == before_effects[1:]
    row = execution_row(
        e2e_admin_conn,
        sandbox.organization_id,
        UUID(proposal["id"]),
        affected_id,
    )
    assert row[1] == "rejected"
    assert row[4] is None and row[5] is None
    assert row[6] == "STALE_RECOVERY_PROPOSAL"
