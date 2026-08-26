from uuid import UUID, uuid4

import pytest

from request_engine.platform.db.session import SessionFactory

from .f4_capacity_support import f4_actor, seed_today_schedule
from .operational_support import PgConnection
from .tenant_sandbox import auth, client_with_actors, seed_tenant_sandbox


@pytest.mark.asyncio
@pytest.mark.e2e
@pytest.mark.postgres
@pytest.mark.invariant
@pytest.mark.contract
@pytest.mark.adversarial
@pytest.mark.capacity
@pytest.mark.provenance
@pytest.mark.security
async def test_f4_projection_is_explainable_read_only_and_customer_safe(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = seed_tenant_sandbox(e2e_admin_conn, "f4-acceptance")
    seed_today_schedule(e2e_admin_conn, sandbox)
    actor = f4_actor(sandbox)
    async with client_with_actors(e2e_session_factory, {sandbox.token: actor}) as client:
        workload = await client.post(
            "/v1/live-workloads",
            json={"workload_key": "follow-up", "display_name": "Follow-up"},
            headers=auth(sandbox, idempotency_key=f"workload-{uuid4().hex}"),
        )
        assert workload.status_code == 201, workload.text
        workload_id = UUID(workload.json()["id"])
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
            json={"workload_classification_id": str(workload_id), "duration_seconds": 1200},
            headers=auth(sandbox, idempotency_key=f"estimate-{uuid4().hex}"),
        )
        assert scope.status_code == estimate.status_code == 201
        checked_in = await client.post(
            f"/v1/queues/{sandbox.queue_id}/check-in",
            json={
                "subject_party_id": str(sandbox.party_id),
                "expected_workload_classification_id": str(workload_id),
            },
            headers=auth(sandbox, idempotency_key=f"checkin-{uuid4().hex}"),
        )
        assert checked_in.status_code == 201, checked_in.text
        entry_id = UUID(checked_in.json()["id"])
        entry_before = e2e_admin_conn.execute(
            "SELECT to_jsonb(q) FROM request_engine.queue_entries q WHERE id=%s", (entry_id,)
        ).fetchone()
        claims_before = e2e_admin_conn.execute(
            "SELECT count(*) FROM request_engine.capacity_claims WHERE organization_id=%s",
            (sandbox.organization_id,),
        ).fetchone()
        staff = await client.get(
            f"/v1/live-capacity/queues/{sandbox.queue_id}", headers=auth(sandbox)
        )
        intake = await client.get(
            f"/v1/live-capacity/queues/{sandbox.queue_id}/evaluate-intake",
            params={"workload_classification_id": str(workload_id)},
            headers=auth(sandbox),
        )
        customer = await client.get(
            f"/v1/live-capacity/queues/{sandbox.queue_id}/customer",
            params={"subject_party_id": str(sandbox.party_id)},
            headers=auth(sandbox),
        )
        assert staff.status_code == intake.status_code == customer.status_code == 200
        body = staff.json()
        assert body["projected_remaining_workload_seconds"] == 1200
        assert body["remaining_operational_seconds"] >= 1200
        assert len(body["items"]) == 1 and UUID(body["items"][0]["key"]) == entry_id
        assert intake.json()["estimated_duration_seconds"] == 1200
        assert intake.json()["fits_within_effective_availability"] is True
        assert set(customer.json()) == {
            "observed_at",
            "entries_ahead",
            "estimated_wait_seconds",
            "estimated_start",
        }
        assert customer.json()["entries_ahead"] == 0

    assert (
        e2e_admin_conn.execute(
            "SELECT to_jsonb(q) FROM request_engine.queue_entries q WHERE id=%s", (entry_id,)
        ).fetchone()
        == entry_before
    )
    assert (
        e2e_admin_conn.execute(
            "SELECT count(*) FROM request_engine.capacity_claims WHERE organization_id=%s",
            (sandbox.organization_id,),
        ).fetchone()
        == claims_before
    )
