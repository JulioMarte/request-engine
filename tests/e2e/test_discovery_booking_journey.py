from __future__ import annotations

from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from request_engine.platform.db.session import SessionFactory

from .contextual_supply_support import contextualize_sandbox
from .discovery_runtime_support import discovery_client
from .discovery_seed_support import create_classification, publish_sandbox, search_body
from .operational_support import PgConnection, RuntimeCredentialsLike
from .tenant_sandbox import auth, client_for, seed_tenant_sandbox


@pytest.mark.asyncio
@pytest.mark.e2e
@pytest.mark.postgres
@pytest.mark.contract
@pytest.mark.provenance
@pytest.mark.security
async def test_discovery_crosses_two_tenants_and_books_selected_handoff(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
    app_runtime_credentials: RuntimeCredentialsLike,
) -> None:
    tenant_a = seed_tenant_sandbox(e2e_admin_conn, "discovery-a")
    tenant_b = seed_tenant_sandbox(e2e_admin_conn, "discovery-b")
    contextual_a = contextualize_sandbox(e2e_admin_conn, tenant_a)
    contextualize_sandbox(e2e_admin_conn, tenant_b)
    classification_id, classification_key = create_classification(e2e_admin_conn)
    publish_sandbox(
        e2e_admin_conn, tenant_a, classification_id, latitude=19.8000, longitude=-70.7000
    )
    publish_sandbox(
        e2e_admin_conn, tenant_b, classification_id, latitude=19.8005, longitude=-70.7005
    )

    async with discovery_client(
        e2e_admin_conn,
        e2e_session_factory,
        app_runtime_credentials.database_url,
    ) as discovery:
        response = await discovery.post(
            "/v1/discovery/supply/search", json=search_body(classification_key)
        )
    assert response.status_code == 200, response.text
    options = cast(list[dict[str, Any]], response.json())
    organizations = {UUID(item["organization_id"]) for item in options}
    assert {tenant_a.organization_id, tenant_b.organization_id} <= organizations
    selected = next(
        item for item in options if item["organization_id"] == str(tenant_a.organization_id)
    )
    assert str(selected["option_id"]).startswith("discoopt_v1.")
    assert Decimal(str(selected["amount"])) == Decimal("4000")
    assert selected["planned_duration_minutes"] == 45

    async with client_for(e2e_session_factory, tenant_a) as booking:
        booked = await booking.post(
            "/v1/appointments",
            json={
                "option_id": selected["option_id"],
                "subject_party_id": str(tenant_a.party_id),
            },
            headers=auth(tenant_a, idempotency_key=f"discovery-book-{uuid4().hex}"),
        )
    assert booked.status_code == 201, booked.text
    reservation_id = UUID(booked.json()["id"])

    claim = e2e_admin_conn.execute(
        "SELECT resource_location_assignment_id FROM request_engine.capacity_claims "
        "WHERE reservation_id = %s AND status = 'active'",
        (reservation_id,),
    ).fetchone()
    assert claim == (contextual_a.assignment_id,)
    commitment = e2e_admin_conn.execute(
        "SELECT amount, currency, planned_duration_minutes FROM "
        "request_engine.reservation_commercial_commitments WHERE reservation_id = %s",
        (reservation_id,),
    ).fetchone()
    assert commitment == (Decimal("4000.000000"), "DOP", 45)
    consumed = e2e_admin_conn.execute(
        "SELECT count(*) FROM request_engine.discovery_booking_handoffs "
        "WHERE consumed_reservation_id = %s",
        (reservation_id,),
    ).fetchone()
    assert consumed == (1,)
