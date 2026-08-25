from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from request_engine.platform.db.session import SessionFactory

from .contextual_supply_support import contextualize_sandbox
from .f3_acceptance_support import (
    acceptance_actor,
    capacity_claim_snapshot,
    create_workload,
    reservation_snapshot,
    seed_walk_in_subject,
)
from .operational_support import PgConnection
from .tenant_sandbox import auth, client_with_actors, first_slot, seed_tenant_sandbox


@pytest.mark.asyncio
@pytest.mark.e2e
@pytest.mark.postgres
@pytest.mark.invariant
@pytest.mark.contract
@pytest.mark.provenance
async def test_reservation_to_completed_service_is_one_authoritative_f3_journey(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = seed_tenant_sandbox(e2e_admin_conn, "f3-acceptance")
    contextualize_sandbox(e2e_admin_conn, sandbox)
    actor = acceptance_actor(sandbox)
    async with client_with_actors(e2e_session_factory, {sandbox.token: actor}) as client:
        expected_id = await create_workload(client, sandbox, "consultation", "Consultation")
        actual_id = await create_workload(client, sandbox, "procedure", "Procedure")
        slot = await first_slot(client, sandbox)
        booked = await client.post(
            "/v1/appointments",
            json={"option_id": str(slot["option_id"]), "subject_party_id": str(sandbox.party_id)},
            headers=auth(sandbox, idempotency_key=f"book-{uuid4().hex}"),
        )
        assert booked.status_code == 201, booked.text
        reservation_id = UUID(cast(dict[str, Any], booked.json())["id"])
        reservation_before = reservation_snapshot(e2e_admin_conn, reservation_id)
        claims_before = capacity_claim_snapshot(e2e_admin_conn, reservation_id)

        checked_in = await client.post(
            f"/v1/queues/{sandbox.queue_id}/check-in",
            json={
                "subject_party_id": str(sandbox.party_id),
                "reservation_id": str(reservation_id),
                "expected_workload_classification_id": str(expected_id),
            },
            headers=auth(sandbox, idempotency_key=f"checkin-{uuid4().hex}"),
        )
        assert checked_in.status_code == 201, checked_in.text
        entry_id = UUID(checked_in.json()["id"])
        walk_in_party = seed_walk_in_subject(e2e_admin_conn, sandbox)
        walk_in = await client.post(
            f"/v1/queues/{sandbox.queue_id}/check-in",
            json={"subject_party_id": str(walk_in_party)},
            headers=auth(sandbox, idempotency_key=f"walkin-{uuid4().hex}"),
        )
        assert walk_in.status_code == 201, walk_in.text

        called = await client.post(
            f"/v1/queues/{sandbox.queue_id}/call-next",
            headers=auth(sandbox, idempotency_key=f"call-{uuid4().hex}"),
        )
        assert called.status_code == 200, called.text
        assert UUID(called.json()["id"]) == entry_id
        started = await client.post(
            f"/v1/queue-entries/{entry_id}/service/start",
            json={
                "resource_id": str(sandbox.resource_id),
                "location_id": str(sandbox.location_id),
                "expected_queue_revision": called.json()["revision"],
            },
            headers=auth(sandbox, idempotency_key=f"start-{uuid4().hex}"),
        )
        assert started.status_code == 201, started.text
        session_id = UUID(started.json()["id"])
        paused = await client.post(
            f"/v1/service-sessions/{session_id}/pause",
            json={"expected_revision": started.json()["revision"], "kind": "administrative"},
            headers=auth(sandbox, idempotency_key=f"pause-{uuid4().hex}"),
        )
        resumed = await client.post(
            f"/v1/service-sessions/{session_id}/resume",
            json={"expected_revision": paused.json()["revision"]},
            headers=auth(sandbox, idempotency_key=f"resume-{uuid4().hex}"),
        )
        completed = await client.post(
            f"/v1/service-sessions/{session_id}/complete",
            json={
                "expected_revision": resumed.json()["revision"],
                "actual_workload_classification_id": str(actual_id),
            },
            headers=auth(sandbox, idempotency_key=f"complete-{uuid4().hex}"),
        )
        assert paused.status_code == resumed.status_code == completed.status_code == 200
        live = await client.get(f"/v1/queues/{sandbox.queue_id}/staff", headers=auth(sandbox))
        assert [UUID(item["queue_entry_id"]) for item in live.json()] == [UUID(walk_in.json()["id"])]

    assert reservation_snapshot(e2e_admin_conn, reservation_id) == reservation_before
    assert capacity_claim_snapshot(e2e_admin_conn, reservation_id) == claims_before
    assert e2e_admin_conn.execute(
        "SELECT status,expected_workload_classification_id FROM request_engine.queue_entries WHERE id=%s",
        (entry_id,),
    ).fetchone() == ("completed", expected_id)
    session = e2e_admin_conn.execute(
        "SELECT status,actual_workload_classification_id FROM request_engine.service_sessions WHERE id=%s",
        (session_id,),
    ).fetchone()
    assert session == ("completed", actual_id) and actual_id != expected_id
    interruption = e2e_admin_conn.execute(
        "SELECT kind,ended_at IS NOT NULL FROM request_engine.service_session_interruptions WHERE service_session_id=%s",
        (session_id,),
    ).fetchone()
    assert interruption == ("administrative", True)
