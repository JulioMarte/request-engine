from __future__ import annotations

from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from request_engine.platform.db.session import SessionFactory

from .contextual_supply_support import ContextualSupply, contextualize_sandbox
from .evidence import durable_snapshot
from .operational_support import PgConnection
from .tenant_sandbox import TenantSandbox, auth, client_for, first_slot, seed_tenant_sandbox


def _world(conn: PgConnection) -> tuple[TenantSandbox, ContextualSupply]:
    sandbox = seed_tenant_sandbox(conn, "contextual-e2e")
    return sandbox, contextualize_sandbox(conn, sandbox)


async def _book(client: AsyncClient, sandbox: TenantSandbox, option_id: object) -> dict[str, Any]:
    response = await client.post(
        "/v1/appointments",
        json={"option_id": str(option_id), "subject_party_id": str(sandbox.party_id)},
        headers=auth(sandbox, idempotency_key=f"book-{uuid4().hex}"),
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


@pytest.mark.asyncio
@pytest.mark.e2e
@pytest.mark.postgres
@pytest.mark.contract
@pytest.mark.provenance
async def test_contextual_public_journey_persists_exact_provenance(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox, contextual = _world(e2e_admin_conn)
    async with client_for(e2e_session_factory, sandbox) as client:
        business = await client.get("/v1/business", headers=auth(sandbox))
        assert business.status_code == 200
        assert str(sandbox.location_id) in {item["id"] for item in business.json()["locations"]}

        catalog = await client.get(
            "/v1/catalog/offerings",
            params={
                "location_id": str(sandbox.location_id),
                "effective_at": "2030-01-07T13:00:00Z",
            },
            headers=auth(sandbox),
        )
        assert catalog.status_code == 200
        assert str(sandbox.offering_id) in {item["id"] for item in catalog.json()}

        slot = await first_slot(client, sandbox)
        assert slot["location_id"] == str(sandbox.location_id)
        assert slot["planned_duration_minutes"] == 45
        assert Decimal(str(slot["amount"])) == Decimal("4000")
        assert slot["currency"] == "DOP"
        reservation = await _book(client, sandbox, slot["option_id"])

    reservation_id = UUID(reservation["id"])
    claim = e2e_admin_conn.execute(
        "SELECT resource_location_assignment_id FROM request_engine.capacity_claims "
        "WHERE reservation_id = %s AND status = 'active'",
        (reservation_id,),
    ).fetchone()
    assert claim == (contextual.assignment_id,)
    commitment = e2e_admin_conn.execute(
        "SELECT amount, currency, planned_duration_minutes FROM "
        "request_engine.reservation_commercial_commitments WHERE reservation_id = %s",
        (reservation_id,),
    ).fetchone()
    assert commitment == (Decimal("4000.000000"), "DOP", 45)
    sources = e2e_admin_conn.execute(
        "SELECT booking_context_terms_id FROM "
        "request_engine.reservation_commercial_commitment_context_terms WHERE reservation_id = %s",
        (reservation_id,),
    ).fetchall()
    assert sources == [(contextual.context_terms_id,)]


@pytest.mark.asyncio
@pytest.mark.e2e
@pytest.mark.postgres
@pytest.mark.contract
@pytest.mark.adversarial
async def test_stale_contextual_option_is_http_409_without_partial_effects(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox, contextual = _world(e2e_admin_conn)
    async with client_for(e2e_session_factory, sandbox) as client:
        slot = await first_slot(client, sandbox)
        e2e_admin_conn.execute(
            "UPDATE request_engine.booking_context_terms SET amount = 4100 "
            "WHERE organization_id = %s AND id = %s",
            (sandbox.organization_id, contextual.context_terms_id),
        )
        before = durable_snapshot(e2e_admin_conn)
        response = await client.post(
            "/v1/appointments",
            json={"option_id": slot["option_id"], "subject_party_id": str(sandbox.party_id)},
            headers=auth(sandbox, idempotency_key=f"stale-{uuid4().hex}"),
        )
    assert response.status_code == 409
    assert response.json()["code"] == "appointment_option_stale"
    assert response.json()["resolution"] == "refresh_and_retry"
    assert durable_snapshot(e2e_admin_conn) == before


@pytest.mark.asyncio
@pytest.mark.e2e
@pytest.mark.postgres
@pytest.mark.contract
@pytest.mark.adversarial
async def test_contextual_reschedule_fails_closed_without_mutation(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox, _ = _world(e2e_admin_conn)
    async with client_for(e2e_session_factory, sandbox) as client:
        reservation = await _book(client, sandbox, (await first_slot(client, sandbox))["option_id"])
        replacement = await first_slot(client, sandbox)
        before = durable_snapshot(e2e_admin_conn)
        response = await client.post(
            f"/v1/appointments/{reservation['id']}/reschedule",
            json={
                "option_id": replacement["option_id"],
                "expected_revision": reservation["revision"],
            },
            headers=auth(sandbox, idempotency_key=f"reschedule-{uuid4().hex}"),
        )
    assert response.status_code == 422
    assert response.json()["code"] == "contextual_commitment_unsupported"
    assert durable_snapshot(e2e_admin_conn) == before
