from __future__ import annotations

from typing import cast
from uuid import UUID, uuid4

import pytest

from request_engine.platform.db.session import SessionFactory

from .f5_delay_communication_support import (
    add_delay_walk_in,
    delay_incident_row,
    impact_action_row,
    impact_task_row,
    open_delay_incident,
    recovery_fact_counts,
)
from .f5_recovery_assertions import outbox_for_task, reservation_state
from .f5_recovery_support import f5_actor
from .f5_recovery_world import prepare_recovery_world
from .operational_support import PgConnection
from .tenant_sandbox import auth, client_with_actors, seed_tenant_sandbox

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.e2e,
    pytest.mark.postgres,
    pytest.mark.contract,
    pytest.mark.invariant,
    pytest.mark.provenance,
]


async def test_f5_delay_impact_communication_dedupes_without_reservation_mutation(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = seed_tenant_sandbox(e2e_admin_conn, "f5-delay-communication")
    actors = {sandbox.token: f5_actor(sandbox)}
    async with client_with_actors(e2e_session_factory, actors) as client:
        world = await prepare_recovery_world(
            client,
            e2e_admin_conn,
            sandbox,
            capacity_slots=10,
        )
        await add_delay_walk_in(client, e2e_admin_conn, sandbox, world)

    incident_id, revision = await open_delay_incident(
        e2e_admin_conn,
        e2e_session_factory,
        sandbox,
    )
    assert delay_incident_row(e2e_admin_conn, sandbox) == ("delay", "open", revision)

    dedupe_key = f"operational-recovery:{incident_id}:impact:{sandbox.party_id}:{revision}"
    reservations_before = {
        reservation: reservation_state(e2e_admin_conn, reservation)
        for reservation in world.reservations
    }
    path = f"/v1/operational-recovery/incidents/{incident_id}/communicate-impact"
    body: dict[str, object] = {
        "expected_source_revision": revision,
        "recipient_party_id": str(sandbox.party_id),
        "message": "Your provider is running behind schedule today.",
    }
    first_key = f"f5-impact-{uuid4().hex}"
    async with client_with_actors(e2e_session_factory, actors) as client:
        first = await client.post(path, json=body, headers=auth(sandbox, idempotency_key=first_key))
        replay = await client.post(
            path, json=body, headers=auth(sandbox, idempotency_key=first_key)
        )
        retry = await client.post(
            path, json=body, headers=auth(sandbox, idempotency_key=f"f5-impact-{uuid4().hex}")
        )

    assert first.status_code == replay.status_code == retry.status_code == 200
    assert first.json()["action_kind"] == "communicate_impact"
    assert first.json()["status"] == "succeeded"
    first_action = UUID(first.json()["id"])
    assert UUID(replay.json()["id"]) == first_action
    retry_action = UUID(retry.json()["id"])
    assert retry_action != first_action
    assert retry.json()["status"] == "succeeded"
    first_steps = first.json()["owner_steps"]["communications"]
    retry_steps = retry.json()["owner_steps"]["communications"]
    assert retry_steps["communication_task_id"] == first_steps["communication_task_id"]
    assert retry_steps["dedupe_key"] == dedupe_key

    assert impact_action_row(e2e_admin_conn, sandbox.organization_id, first_action) == (
        "communicate_impact",
        "succeeded",
        revision,
        sandbox.principal_id,
        None,
    )
    assert impact_action_row(e2e_admin_conn, sandbox.organization_id, retry_action)[:2] == (
        "communicate_impact",
        "succeeded",
    )
    task = impact_task_row(e2e_admin_conn, sandbox.organization_id, dedupe_key)
    task_id = cast(UUID, task[0])
    assert task[1:] == (
        sandbox.party_id,
        "operational_recovery_rescheduled",
        "OperationalRecoveryExecution",
        incident_id,
        "pending",
        dedupe_key,
    )
    assert len(outbox_for_task(e2e_admin_conn, sandbox.organization_id, task_id)) == 1
    assert recovery_fact_counts(e2e_admin_conn, sandbox.organization_id) == (1, 0)
    assert {
        reservation: reservation_state(e2e_admin_conn, reservation)
        for reservation in world.reservations
    } == reservations_before
