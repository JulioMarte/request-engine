from __future__ import annotations

from decimal import Decimal
from typing import cast
from uuid import UUID, uuid4

import pytest

from request_engine.platform.db.session import SessionFactory

from .f4_capacity_support import seed_today_schedule
from .f4_operational_day_support import configure_projection
from .f5_booking_fixture import five_minute_sandbox
from .f5_contextual_support import contextualize_recovery_supply, restrict_contextual_capacity
from .f5_recovery_assertions import create_proposal, execute_proposal
from .f5_recovery_support import book_commitments, f5_actor
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


async def test_f5_contextual_reschedule_preserves_assignment_and_commercial_commitment(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    base = seed_tenant_sandbox(e2e_admin_conn, "f5-contextual-reschedule")
    sandbox = five_minute_sandbox(e2e_admin_conn, base)
    seed_today_schedule(e2e_admin_conn, sandbox)
    supply = contextualize_recovery_supply(e2e_admin_conn, sandbox)
    actors = {sandbox.token: f5_actor(sandbox)}
    async with client_with_actors(e2e_session_factory, actors) as client:
        await configure_projection(client, sandbox)
        _, slots = await book_commitments(client, e2e_admin_conn, sandbox)
        restrict_contextual_capacity(
            e2e_admin_conn,
            sandbox,
            supply,
            slots,
            count=6,
        )
        proposal = await create_proposal(client, sandbox)
        affected = proposal["affected"]
        assert affected
        item = next(value for value in affected if value["target"] is not None)
        target = item["target"]
        assert target["configuration_fingerprint"]
        assert target["resources"][0]["resource_location_assignment_id"] == str(
            supply.assignment_id
        )
        reservation_id = UUID(cast(str, item["reservation_id"]))
        before = _commercial_commitment(e2e_admin_conn, reservation_id)
        response = await execute_proposal(
            client,
            sandbox,
            proposal,
            reservation_id,
            idempotency_key=f"f5-contextual-execute-{uuid4().hex}",
            notify=False,
        )
    assert response.status_code == 200, response.text
    claim = e2e_admin_conn.execute(
        "SELECT resource_location_assignment_id FROM request_engine.capacity_claims "
        "WHERE reservation_id=%s AND status='active'",
        (reservation_id,),
    ).fetchone()
    assert claim == (supply.assignment_id,)
    assert _commercial_commitment(e2e_admin_conn, reservation_id) == before
    assert before[:3] == (Decimal("4000.000000"), "DOP", 5)


def _commercial_commitment(conn: PgConnection, reservation_id: UUID) -> tuple[object, ...]:
    row = conn.execute(
        "SELECT amount,currency,planned_duration_minutes,configuration_fingerprint "
        "FROM request_engine.reservation_commercial_commitments WHERE reservation_id=%s",
        (reservation_id,),
    ).fetchone()
    assert row is not None
    return tuple(row)
