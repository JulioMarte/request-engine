from __future__ import annotations

from collections.abc import Mapping
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
from .tenant_sandbox import TenantSandbox, client_with_actors, seed_tenant_sandbox

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.e2e,
    pytest.mark.postgres,
    pytest.mark.contract,
    pytest.mark.provenance,
    pytest.mark.capacity,
]


@pytest.mark.parametrize("change", ["price", "location", "assignment"])
async def test_f5_contextual_proposal_fails_closed_after_material_configuration_change(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
    change: str,
) -> None:
    base = seed_tenant_sandbox(e2e_admin_conn, f"f5-contextual-stale-{change}")
    sandbox = five_minute_sandbox(e2e_admin_conn, base)
    seed_today_schedule(e2e_admin_conn, sandbox)
    supply = contextualize_recovery_supply(e2e_admin_conn, sandbox)
    actors = {sandbox.token: f5_actor(sandbox)}
    async with client_with_actors(e2e_session_factory, actors) as client:
        await configure_projection(client, sandbox)
        _, slots = await book_commitments(client, e2e_admin_conn, sandbox)
        restrict_contextual_capacity(e2e_admin_conn, sandbox, supply, slots, count=6)
        proposal = await create_proposal(client, sandbox)
        item = next(value for value in proposal["affected"] if value["target"] is not None)
        reservation_id = UUID(cast(str, item["reservation_id"]))
        target = cast(Mapping[str, object], item["target"])
        before = _reservation_state(e2e_admin_conn, reservation_id)
        _apply_change(e2e_admin_conn, sandbox, supply.assignment_id, target, change)
        response = await execute_proposal(
            client,
            sandbox,
            proposal,
            reservation_id,
            idempotency_key=f"f5-contextual-stale-{change}-{uuid4().hex}",
            notify=False,
        )
    assert response.status_code == 409, response.text
    assert _reservation_state(e2e_admin_conn, reservation_id) == before


def _apply_change(
    conn: PgConnection,
    sandbox: TenantSandbox,
    assignment_id: UUID,
    target: Mapping[str, object],
    change: str,
) -> None:
    if change == "price":
        conn.execute(
            "UPDATE request_engine.booking_context_terms SET amount=amount+100 "
            "WHERE organization_id=%s AND resource_location_assignment_id=%s",
            (sandbox.organization_id, assignment_id),
        )
        return
    table = (
        "location_hours_exceptions"
        if change == "location"
        else "resource_location_schedule_exceptions"
    )
    owner_column = "location_id" if change == "location" else "resource_location_assignment_id"
    owner_id = sandbox.location_id if change == "location" else assignment_id
    conn.execute(
        f"INSERT INTO request_engine.{table} "
        f"(organization_id,{owner_column},during,exception_kind,reason) "
        "VALUES (%s,%s,tstzrange(%s,%s,'[)'),'unavailable','F5 stale race')",
        (
            sandbox.organization_id,
            owner_id,
            cast(str, target["start_at"]),
            cast(str, target["end_at"]),
        ),
    )


def _reservation_state(conn: PgConnection, reservation_id: UUID) -> tuple[object, ...]:
    row = conn.execute(
        "SELECT r.revision, lower(r.during), upper(r.during), c.resource_location_assignment_id, "
        "m.amount, m.currency, m.planned_duration_minutes, m.configuration_fingerprint "
        "FROM request_engine.reservations r JOIN request_engine.capacity_claims c "
        "ON c.reservation_id=r.id AND c.status='active' "
        "JOIN request_engine.reservation_commercial_commitments m ON m.reservation_id=r.id "
        "WHERE r.id=%s",
        (reservation_id,),
    ).fetchone()
    assert row is not None
    return tuple(row)
