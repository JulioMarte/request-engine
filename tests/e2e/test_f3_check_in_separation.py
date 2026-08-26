from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext

from .contextual_supply_support import contextualize_sandbox
from .operational_support import PgConnection
from .tenant_sandbox import (
    TenantSandbox,
    actor_for,
    auth,
    client_with_actors,
    first_slot,
    seed_tenant_sandbox,
)


def _reservation_snapshot(conn: PgConnection, reservation_id: UUID) -> Any:
    row = conn.execute(
        "SELECT to_jsonb(r) FROM request_engine.reservations r WHERE id = %s",
        (reservation_id,),
    ).fetchone()
    assert row is not None
    return row[0]


def _capacity_claim_snapshot(conn: PgConnection, reservation_id: UUID) -> list[Any]:
    rows = conn.execute(
        "SELECT to_jsonb(c) FROM request_engine.capacity_claims c "
        "WHERE reservation_id = %s ORDER BY id",
        (reservation_id,),
    ).fetchall()
    return [row[0] for row in rows]


def _seed_walk_in_subject(conn: PgConnection, sandbox: TenantSandbox) -> UUID:
    row = conn.execute(
        "INSERT INTO request_engine.parties "
        "(organization_id,party_kind,display_name) VALUES (%s,'person',%s) RETURNING id",
        (sandbox.organization_id, f"Walk-in {uuid4().hex[:8]}"),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


@pytest.mark.asyncio
@pytest.mark.e2e
@pytest.mark.postgres
@pytest.mark.invariant
@pytest.mark.contract
@pytest.mark.adversarial
@pytest.mark.provenance
async def test_check_in_keeps_reservation_planning_separate_and_walk_in_reservation_free(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = seed_tenant_sandbox(e2e_admin_conn, "f3-check-in-separation")
    contextualize_sandbox(e2e_admin_conn, sandbox)
    base_actor = actor_for(sandbox)
    actor = ActorContext(
        organization_id=base_actor.organization_id,
        principal_id=base_actor.principal_id,
        capabilities=base_actor.capabilities | frozenset({"queue.check_in"}),
    )
    async with client_with_actors(e2e_session_factory, {sandbox.token: actor}) as client:
        slot = await first_slot(client, sandbox)
        booked = await client.post(
            "/v1/appointments",
            json={
                "option_id": str(slot["option_id"]),
                "subject_party_id": str(sandbox.party_id),
            },
            headers=auth(sandbox, idempotency_key=f"book-{uuid4().hex}"),
        )
        assert booked.status_code == 201, booked.text
        reservation = cast(dict[str, Any], booked.json())
        reservation_id = UUID(reservation["id"])
        before_reservation = _reservation_snapshot(e2e_admin_conn, reservation_id)
        before_claims = _capacity_claim_snapshot(e2e_admin_conn, reservation_id)

        scheduled = await client.post(
            f"/v1/queues/{sandbox.queue_id}/check-in",
            json={
                "subject_party_id": str(sandbox.party_id),
                "reservation_id": str(reservation_id),
            },
            headers=auth(sandbox, idempotency_key=f"check-in-{uuid4().hex}"),
        )
        assert scheduled.status_code == 201, scheduled.text
        assert scheduled.json()["reservation_id"] == str(reservation_id)
        assert _reservation_snapshot(e2e_admin_conn, reservation_id) == before_reservation
        assert _capacity_claim_snapshot(e2e_admin_conn, reservation_id) == before_claims

        walk_in_party_id = _seed_walk_in_subject(e2e_admin_conn, sandbox)
        reservation_count = e2e_admin_conn.execute(
            "SELECT count(*) FROM request_engine.reservations WHERE organization_id = %s",
            (sandbox.organization_id,),
        ).fetchone()
        walk_in = await client.post(
            f"/v1/queues/{sandbox.queue_id}/check-in",
            json={"subject_party_id": str(walk_in_party_id)},
            headers=auth(sandbox, idempotency_key=f"walk-in-{uuid4().hex}"),
        )

    assert walk_in.status_code == 201, walk_in.text
    assert walk_in.json()["reservation_id"] is None
    assert (
        e2e_admin_conn.execute(
            "SELECT count(*) FROM request_engine.reservations WHERE organization_id = %s",
            (sandbox.organization_id,),
        ).fetchone()
        == reservation_count
    )
    queue_rows = e2e_admin_conn.execute(
        "SELECT subject_party_id,reservation_id FROM request_engine.queue_entries "
        "WHERE organization_id = %s AND service_queue_id = %s ORDER BY admitted_at,id",
        (sandbox.organization_id, sandbox.queue_id),
    ).fetchall()
    assert queue_rows == [(sandbox.party_id, reservation_id), (walk_in_party_id, None)]
