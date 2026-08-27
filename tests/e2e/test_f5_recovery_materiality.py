from uuid import UUID, uuid4

import pytest

from request_engine.platform.db.session import SessionFactory

from .f3_acceptance_assertions import seed_walk_in_subject
from .f5_recovery_assertions import create_proposal, recovery_counts, reservation_state
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


async def test_f5_ten_commitments_reduced_to_six_selects_exact_last_four_and_blocks_intake(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = seed_tenant_sandbox(e2e_admin_conn, "f5-materiality")
    actors = {sandbox.token: f5_actor(sandbox)}
    async with client_with_actors(e2e_session_factory, actors) as client:
        world = await prepare_recovery_world(client, e2e_admin_conn, sandbox)
        proposal = await create_proposal(client, sandbox)
        assert proposal["committed_capacity_seconds"] == 3000
        assert proposal["executable_capacity_seconds"] == 1800
        assert proposal["shortfall_seconds"] == 1200
        affected = proposal["affected"]
        expected_ids = world.reservations[6:]
        assert tuple(UUID(item["reservation_id"]) for item in affected) == expected_ids
        assert tuple(item["expected_revision"] for item in affected) == tuple(
            reservation_state(e2e_admin_conn, reservation_id)[0] for reservation_id in expected_ids
        )

        stale_option = world.slots[10]
        rejected = await client.post(
            "/v1/appointments",
            json={
                "option_id": str(stale_option["option_id"]),
                "subject_party_id": str(sandbox.party_id),
            },
            headers=auth(sandbox, idempotency_key=f"f5-broken-intake-{uuid4().hex}"),
        )
        assert rejected.status_code != 201

    confirmed = e2e_admin_conn.execute(
        "SELECT count(*) FROM request_engine.reservations "
        "WHERE organization_id=%s AND status='confirmed'",
        (sandbox.organization_id,),
    ).fetchone()
    assert confirmed == (10,)


async def test_f5_live_walk_in_pressure_expands_material_shortfall_and_affected_set(
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


async def test_f5_proposal_is_read_only_and_uses_booking_generated_replacement_target(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = seed_tenant_sandbox(e2e_admin_conn, "f5-read-only")
    actors = {sandbox.token: f5_actor(sandbox)}
    async with client_with_actors(e2e_session_factory, actors) as client:
        world = await prepare_recovery_world(client, e2e_admin_conn, sandbox)
        before = tuple(
            reservation_state(e2e_admin_conn, reservation_id)
            for reservation_id in world.reservations
        )
        side_effects_before = recovery_counts(e2e_admin_conn, sandbox.organization_id)
        proposal = await create_proposal(client, sandbox)

    targets = [item["target"] for item in proposal["affected"]]
    assert targets and all(target is not None and target["actionable"] for target in targets)
    assert all(
        str(world.replacement_resource_id)
        in {choice["resource_id"] for choice in target["resources"]}
        for target in targets
        if target is not None
    )
    assert (
        tuple(
            reservation_state(e2e_admin_conn, reservation_id)
            for reservation_id in world.reservations
        )
        == before
    )
    assert recovery_counts(e2e_admin_conn, sandbox.organization_id) == side_effects_before
