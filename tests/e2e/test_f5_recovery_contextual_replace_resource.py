from __future__ import annotations

from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from request_engine.platform.db.session import SessionFactory

from .f4_capacity_support import seed_today_schedule
from .f4_operational_day_support import configure_projection
from .f5_booking_fixture import five_minute_sandbox
from .f5_contextual_support import contextualize_recovery_supply, restrict_contextual_capacity
from .f5_recovery_assertions import create_proposal, reservation_state
from .f5_recovery_support import book_commitments, f5_actor
from .f5_replace_resource_support import (
    replace_resource,
    seed_alternate_contextual_supply,
    seed_incident_for_proposal,
)
from .operational_support import PgConnection
from .tenant_sandbox import client_with_actors, seed_tenant_sandbox

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.e2e,
    pytest.mark.postgres,
    pytest.mark.contract,
    pytest.mark.provenance,
    pytest.mark.capacity,
]


async def test_f5_contextual_replace_resource_preserves_time_and_commercial_truth(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    base = seed_tenant_sandbox(e2e_admin_conn, "f5-contextual-replace")
    sandbox = five_minute_sandbox(e2e_admin_conn, base)
    seed_today_schedule(e2e_admin_conn, sandbox)
    source = contextualize_recovery_supply(e2e_admin_conn, sandbox)
    actors = {sandbox.token: f5_actor(sandbox)}
    async with client_with_actors(e2e_session_factory, actors) as client:
        await configure_projection(client, sandbox)
        _, slots = await book_commitments(client, e2e_admin_conn, sandbox)
        restrict_contextual_capacity(e2e_admin_conn, sandbox, source, slots, count=6)
        alternate = seed_alternate_contextual_supply(e2e_admin_conn, sandbox)
        proposal = await create_proposal(client, sandbox)
        item = _replacement_item(proposal, alternate.resource_id)
        target = cast(dict[str, Any], item["replacement_target"])
        reservation_id = UUID(cast(str, item["reservation_id"]))
        before_state = reservation_state(e2e_admin_conn, reservation_id)
        before_commercial = _commercial_commitment(e2e_admin_conn, reservation_id)
        _assert_replacement_target(item, target, alternate.resource_id, alternate.assignment_id)
        incident_id = seed_incident_for_proposal(e2e_admin_conn, sandbox, proposal)
        key = f"f5-contextual-replace-{uuid4().hex}"
        response = await replace_resource(
            client,
            sandbox,
            incident_id=incident_id,
            proposal=proposal,
            reservation_id=reservation_id,
            idempotency_key=key,
        )
        replay = await replace_resource(
            client,
            sandbox,
            incident_id=incident_id,
            proposal=proposal,
            reservation_id=reservation_id,
            idempotency_key=key,
        )
    assert response.status_code == 200, response.text
    assert replay.status_code == 200, replay.text
    action = response.json()
    assert action["action_kind"] == "replace_resource"
    assert action["status"] == "succeeded"
    assert replay.json()["id"] == action["id"]
    after_state = reservation_state(e2e_admin_conn, reservation_id)
    assert after_state[2:] == before_state[2:]
    assert _commercial_commitment(e2e_admin_conn, reservation_id) == before_commercial
    assert before_commercial[:3] == (Decimal("4000.000000"), "DOP", 5)
    _assert_active_claim(
        e2e_admin_conn,
        reservation_id,
        alternate.resource_id,
        alternate.assignment_id,
    )


def _replacement_item(proposal: dict[str, Any], resource_id: UUID) -> dict[str, Any]:
    for value in cast(list[dict[str, Any]], proposal["affected"]):
        target = value.get("replacement_target")
        if target and target["resources"][0]["resource_id"] == str(resource_id):
            return value
    raise AssertionError("proposal did not expose an alternate same-time Resource")


def _assert_replacement_target(
    item: dict[str, Any], target: dict[str, Any], resource_id: UUID, assignment_id: UUID
) -> None:
    assert target["configuration_fingerprint"]
    assert target["start_at"] == item["original_start_at"]
    assert target["end_at"] == item["original_end_at"]
    assert target["resources"][0]["resource_id"] == str(resource_id)
    assert target["resources"][0]["resource_location_assignment_id"] == str(assignment_id)


def _commercial_commitment(conn: PgConnection, reservation_id: UUID) -> tuple[object, ...]:
    row = conn.execute(
        "SELECT amount,currency,planned_duration_minutes,configuration_fingerprint "
        "FROM request_engine.reservation_commercial_commitments WHERE reservation_id=%s",
        (reservation_id,),
    ).fetchone()
    assert row is not None
    return tuple(row)


def _assert_active_claim(
    conn: PgConnection, reservation_id: UUID, resource_id: UUID, assignment_id: UUID
) -> None:
    rows = conn.execute(
        "SELECT resource_id,resource_location_assignment_id FROM request_engine.capacity_claims "
        "WHERE reservation_id=%s AND status='active'",
        (reservation_id,),
    ).fetchall()
    assert rows == [(resource_id, assignment_id)]
