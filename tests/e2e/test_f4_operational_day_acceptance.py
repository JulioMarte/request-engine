from uuid import UUID, uuid4

import pytest

from request_engine.platform.db.session import SessionFactory

from .f3_acceptance_assertions import (
    capacity_claim_snapshot,
    reservation_snapshot,
    seed_walk_in_subject,
)
from .f4_capacity_support import (
    f4_actor,
    seed_live_execution_assignment,
    seed_today_schedule,
)
from .f4_operational_day_support import (
    book_two_same_day,
    call_and_start,
    configure_projection,
    read_projection,
)
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


async def test_f4_operational_day_reprojects_planning_queue_and_service_truth(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = seed_tenant_sandbox(e2e_admin_conn, "f4-operational-day")
    seed_live_execution_assignment(e2e_admin_conn, sandbox)
    seed_today_schedule(e2e_admin_conn, sandbox)
    actors = {sandbox.token: f4_actor(sandbox)}
    async with client_with_actors(e2e_session_factory, actors) as client:
        expected_id, walk_id = await configure_projection(client, sandbox)
        first_reservation, future_reservation = await book_two_same_day(
            client, e2e_admin_conn, sandbox
        )
        reservation_before = reservation_snapshot(e2e_admin_conn, first_reservation)
        claims_before = capacity_claim_snapshot(e2e_admin_conn, first_reservation)
        checked = await client.post(
            f"/v1/queues/{sandbox.queue_id}/check-in",
            json={
                "subject_party_id": str(sandbox.party_id),
                "reservation_id": str(first_reservation),
                "expected_workload_classification_id": str(expected_id),
            },
            headers=auth(sandbox, idempotency_key=f"checkin-{uuid4().hex}"),
        )
        walk_in = await client.post(
            f"/v1/queues/{sandbox.queue_id}/check-in",
            json={
                "subject_party_id": str(seed_walk_in_subject(e2e_admin_conn, sandbox)),
                "expected_workload_classification_id": str(walk_id),
            },
            headers=auth(sandbox, idempotency_key=f"walkin-{uuid4().hex}"),
        )
        assert checked.status_code == walk_in.status_code == 201
        entry_id = UUID(checked.json()["id"])
        walk_entry_id = UUID(walk_in.json()["id"])
        before = await read_projection(client, sandbox)
        assert [UUID(item["key"]) for item in before["items"]] == [
            entry_id,
            walk_entry_id,
            future_reservation,
        ]
        assert before["items"][0]["source"] == "planned_duration"
        assert before["scheduled_committed_workload_seconds"] == 3600
        assert before["projected_remaining_workload_seconds"] == 4800
        assert before["live_vs_scheduled_headroom_delta_seconds"] == -1200

        started = await call_and_start(client, sandbox, entry_id)
        session_id = UUID(started["id"])
        active = await read_projection(client, sandbox)
        assert UUID(active["items"][0]["key"]) == session_id
        assert active["items"][0]["source"] == "planned_duration"
        paused = await client.post(
            f"/v1/service-sessions/{session_id}/pause",
            json={"expected_revision": started["revision"], "kind": "administrative"},
            headers=auth(sandbox, idempotency_key=f"pause-{uuid4().hex}"),
        )
        blocked = await read_projection(client, sandbox)
        assert paused.status_code == 200 and blocked["state"] == "indeterminate"
        assert "open_interruption" in blocked["reasons"]
        resumed = await client.post(
            f"/v1/service-sessions/{session_id}/resume",
            json={"expected_revision": paused.json()["revision"]},
            headers=auth(sandbox, idempotency_key=f"resume-{uuid4().hex}"),
        )
        assert resumed.status_code == 200
        assert (await read_projection(client, sandbox))["state"] != "indeterminate"
        completed = await client.post(
            f"/v1/service-sessions/{session_id}/complete",
            json={
                "expected_revision": resumed.json()["revision"],
                "actual_workload_classification_id": str(expected_id),
            },
            headers=auth(sandbox, idempotency_key=f"complete-{uuid4().hex}"),
        )
        assert completed.status_code == 200, completed.text
        after = await read_projection(client, sandbox)
        assert [UUID(item["key"]) for item in after["items"]] == [
            walk_entry_id,
            future_reservation,
        ]
        assert after["scheduled_committed_workload_seconds"] == 3600
        assert after["projected_remaining_workload_seconds"] == 3000
        assert after["live_vs_scheduled_headroom_delta_seconds"] == 600

    assert reservation_snapshot(e2e_admin_conn, first_reservation) == reservation_before
    assert capacity_claim_snapshot(e2e_admin_conn, first_reservation) == claims_before
