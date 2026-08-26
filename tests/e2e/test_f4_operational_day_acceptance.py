from uuid import UUID, uuid4

import pytest

from request_engine.platform.db.session import SessionFactory

from .f3_acceptance_assertions import (
    capacity_claim_snapshot,
    reservation_snapshot,
    seed_walk_in_subject,
)
from .f4_capacity_support import f4_actor, same_day_slots, seed_today_schedule
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
    seed_today_schedule(e2e_admin_conn, sandbox)
    actor = f4_actor(sandbox)
    async with client_with_actors(e2e_session_factory, {sandbox.token: actor}) as client:
        expected = await client.post(
            "/v1/live-workloads",
            json={"workload_key": "scheduled", "display_name": "Scheduled"},
            headers=auth(sandbox, idempotency_key=f"workload-{uuid4().hex}"),
        )
        walk = await client.post(
            "/v1/live-workloads",
            json={"workload_key": "walk-in", "display_name": "Walk-in"},
            headers=auth(sandbox, idempotency_key=f"workload-{uuid4().hex}"),
        )
        assert expected.status_code == walk.status_code == 201
        expected_id, walk_id = UUID(expected.json()["id"]), UUID(walk.json()["id"])
        scope = await client.post(
            "/v1/live-capacity/projection-policies",
            json={
                "service_queue_id": str(sandbox.queue_id),
                "resource_id": str(sandbox.resource_id),
                "location_id": str(sandbox.location_id),
            },
            headers=auth(sandbox, idempotency_key=f"scope-{uuid4().hex}"),
        )
        estimate = await client.post(
            "/v1/live-capacity/workload-estimate-policies",
            json={"workload_classification_id": str(walk_id), "duration_seconds": 1200},
            headers=auth(sandbox, idempotency_key=f"estimate-{uuid4().hex}"),
        )
        assert scope.status_code == estimate.status_code == 201
        slots = await same_day_slots(client, e2e_admin_conn, sandbox)
        reservations = []
        for slot in slots[:2]:
            booked = await client.post(
                "/v1/appointments",
                json={"option_id": str(slot["option_id"]), "subject_party_id": str(sandbox.party_id)},
                headers=auth(sandbox, idempotency_key=f"book-{uuid4().hex}"),
            )
            assert booked.status_code == 201, booked.text
            reservations.append(UUID(booked.json()["id"]))
        first_reservation, future_reservation = reservations
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
        walk_party = seed_walk_in_subject(e2e_admin_conn, sandbox)
        walk_in = await client.post(
            f"/v1/queues/{sandbox.queue_id}/check-in",
            json={
                "subject_party_id": str(walk_party),
                "expected_workload_classification_id": str(walk_id),
            },
            headers=auth(sandbox, idempotency_key=f"walkin-{uuid4().hex}"),
        )
        assert checked.status_code == walk_in.status_code == 201
        entry_id, walk_entry_id = UUID(checked.json()["id"]), UUID(walk_in.json()["id"])
        before = (await client.get(f"/v1/live-capacity/queues/{sandbox.queue_id}", headers=auth(sandbox))).json()
        assert [UUID(item["key"]) for item in before["items"]] == [entry_id, walk_entry_id, future_reservation]
        assert before["items"][0]["source"] == "planned_duration"
        assert before["scheduled_committed_workload_seconds"] == 3600
        assert before["projected_remaining_workload_seconds"] == 4800
        assert before["live_vs_scheduled_headroom_delta_seconds"] == -1200
        called = await client.post(
            f"/v1/queues/{sandbox.queue_id}/call-next",
            headers=auth(sandbox, idempotency_key=f"call-{uuid4().hex}"),
        )
        started = await client.post(
            f"/v1/queue-entries/{entry_id}/service/start",
            json={"resource_id": str(sandbox.resource_id), "location_id": str(sandbox.location_id), "expected_queue_revision": called.json()["revision"]},
            headers=auth(sandbox, idempotency_key=f"start-{uuid4().hex}"),
        )
        assert called.status_code == 200 and UUID(called.json()["id"]) == entry_id
        assert started.status_code == 201, started.text
        session_id = UUID(started.json()["id"])
        active = (await client.get(f"/v1/live-capacity/queues/{sandbox.queue_id}", headers=auth(sandbox))).json()
        assert UUID(active["items"][0]["key"]) == session_id
        assert active["items"][0]["source"] == "planned_duration"
        paused = await client.post(
            f"/v1/service-sessions/{session_id}/pause",
            json={"expected_revision": started.json()["revision"], "kind": "administrative"},
            headers=auth(sandbox, idempotency_key=f"pause-{uuid4().hex}"),
        )
        blocked = (await client.get(f"/v1/live-capacity/queues/{sandbox.queue_id}", headers=auth(sandbox))).json()
        assert paused.status_code == 200 and blocked["state"] == "indeterminate"
        assert "open_interruption" in blocked["reasons"]
        resumed = await client.post(
            f"/v1/service-sessions/{session_id}/resume",
            json={"expected_revision": paused.json()["revision"]},
            headers=auth(sandbox, idempotency_key=f"resume-{uuid4().hex}"),
        )
        recovered = (await client.get(f"/v1/live-capacity/queues/{sandbox.queue_id}", headers=auth(sandbox))).json()
        assert resumed.status_code == 200 and recovered["state"] != "indeterminate"
        completed = await client.post(
            f"/v1/service-sessions/{session_id}/complete",
            json={"expected_revision": resumed.json()["revision"], "actual_workload_classification_id": str(expected_id)},
            headers=auth(sandbox, idempotency_key=f"complete-{uuid4().hex}"),
        )
        assert completed.status_code == 200, completed.text
        after = (await client.get(f"/v1/live-capacity/queues/{sandbox.queue_id}", headers=auth(sandbox))).json()
        assert [UUID(item["key"]) for item in after["items"]] == [walk_entry_id, future_reservation]
        assert first_reservation not in {UUID(item["key"]) for item in after["items"]}
        assert after["scheduled_committed_workload_seconds"] == 3600
        assert after["projected_remaining_workload_seconds"] == 3000
        assert after["live_vs_scheduled_headroom_delta_seconds"] == 600

    assert reservation_snapshot(e2e_admin_conn, first_reservation) == reservation_before
    assert capacity_claim_snapshot(e2e_admin_conn, first_reservation) == claims_before
