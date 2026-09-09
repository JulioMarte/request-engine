from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient, Response

from request_engine.platform.db.session import SessionFactory

from .f4_capacity_support import seed_today_schedule
from .f4_operational_day_support import configure_projection
from .f5_booking_fixture import five_minute_sandbox
from .f5_contextual_support import contextualize_recovery_supply, restrict_contextual_capacity
from .f5_recovery_assertions import create_proposal, reservation_state
from .f5_recovery_support import book_commitments, f5_actor
from .f5_replace_resource_support import seed_incident_for_proposal
from .operational_support import PgConnection
from .tenant_sandbox import TenantSandbox, auth, client_with_actors, seed_tenant_sandbox

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.e2e,
    pytest.mark.postgres,
    pytest.mark.contract,
    pytest.mark.provenance,
    pytest.mark.capacity,
]


async def test_f5_contextual_reschedule_action_commits_authorized_target(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    base = seed_tenant_sandbox(e2e_admin_conn, "f5-contextual-reschedule-action")
    sandbox = five_minute_sandbox(e2e_admin_conn, base)
    seed_today_schedule(e2e_admin_conn, sandbox)
    supply = contextualize_recovery_supply(e2e_admin_conn, sandbox)
    actors = {sandbox.token: f5_actor(sandbox)}
    async with client_with_actors(e2e_session_factory, actors) as client:
        await configure_projection(client, sandbox)
        _, slots = await book_commitments(client, e2e_admin_conn, sandbox)
        restrict_contextual_capacity(e2e_admin_conn, sandbox, supply, slots, count=6)
        proposal = await create_proposal(client, sandbox)
        item = _reschedule_item(proposal)
        target = cast(dict[str, Any], item["target"])
        reservation_id = UUID(cast(str, item["reservation_id"]))
        before_state = reservation_state(e2e_admin_conn, reservation_id)
        before_commercial = _commercial_commitment(e2e_admin_conn, reservation_id)
        incident_id = seed_incident_for_proposal(e2e_admin_conn, sandbox, proposal)
        key = f"f5-contextual-reschedule-action-{uuid4().hex}"
        response = await _reschedule(client, sandbox, incident_id, proposal, reservation_id, key)
        replay = await _reschedule(client, sandbox, incident_id, proposal, reservation_id, key)
    assert response.status_code == 200, response.text
    assert replay.status_code == 200, replay.text
    action = response.json()
    assert action["action_kind"] == "reschedule"
    assert action["status"] == "succeeded"
    assert replay.json()["id"] == action["id"]
    after_state = reservation_state(e2e_admin_conn, reservation_id)
    assert after_state[0] == cast(int, before_state[0]) + 1
    assert after_state[1] == before_state[1]
    assert cast(datetime, after_state[2]) == datetime.fromisoformat(cast(str, target["start_at"]))
    assert cast(datetime, after_state[3]) == datetime.fromisoformat(cast(str, target["end_at"]))
    assert _commercial_commitment(e2e_admin_conn, reservation_id) == before_commercial
    assert before_commercial[:3] == (Decimal("4000.000000"), "DOP", 5)
    _assert_target_claim(e2e_admin_conn, reservation_id, target)


def _reschedule_item(proposal: dict[str, Any]) -> dict[str, Any]:
    for item in cast(list[dict[str, Any]], proposal["affected"]):
        target = item.get("target")
        if target is not None and target.get("configuration_fingerprint"):
            return item
    raise AssertionError("proposal did not expose a contextual reschedule target")


async def _reschedule(
    client: AsyncClient,
    sandbox: TenantSandbox,
    incident_id: UUID,
    proposal: dict[str, Any],
    reservation_id: UUID,
    idempotency_key: str,
) -> Response:
    checkpoint = cast(dict[str, Any], proposal["source_checkpoint"])
    return await client.post(
        f"/v1/operational-recovery/incidents/{incident_id}/reschedule",
        json={
            "expected_source_revision": checkpoint["recovery_source_revision"],
            "proposal_id": proposal["id"],
            "reservation_id": str(reservation_id),
            "expected_source_fingerprint": proposal["source_fingerprint"],
            "expected_proposal_fingerprint": proposal["proposal_fingerprint"],
            "allow_subject_override": False,
        },
        headers=auth(sandbox, idempotency_key=idempotency_key),
    )


def _commercial_commitment(conn: PgConnection, reservation_id: UUID) -> tuple[object, ...]:
    row = conn.execute(
        "SELECT amount,currency,planned_duration_minutes,configuration_fingerprint "
        "FROM request_engine.reservation_commercial_commitments WHERE reservation_id=%s",
        (reservation_id,),
    ).fetchone()
    assert row is not None
    return tuple(row)


def _assert_target_claim(conn: PgConnection, reservation_id: UUID, target: dict[str, Any]) -> None:
    resource = cast(dict[str, Any], target["resources"][0])
    rows = conn.execute(
        "SELECT resource_id,resource_location_assignment_id FROM request_engine.capacity_claims "
        "WHERE reservation_id=%s AND status='active'",
        (reservation_id,),
    ).fetchall()
    assert rows == [
        (
            UUID(cast(str, resource["resource_id"])),
            UUID(cast(str, resource["resource_location_assignment_id"])),
        )
    ]
