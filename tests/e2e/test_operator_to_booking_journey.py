from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from request_engine.entrypoints.http.operational_app import create_operational_app
from request_engine.platform.db.session import SessionFactory

from .operational_support import PgConnection
from .tenant_sandbox import SandboxResolver, actor_for, auth, client_for, first_slot, seed_tenant_sandbox


def _grant_operational_scopes(conn: PgConnection, sandbox) -> None:
    for scope in ("operations.manage_profile", "operations.manage_supply", "operations.manage_terms"):
        conn.execute(
            """
            INSERT INTO request_engine.representations (
                organization_id, principal_id, represented_party_id,
                authority_kind, scope_key, valid_until
            ) VALUES (%s, %s, %s, 'delegated', %s, clock_timestamp() + interval '1 day')
            """,
            (sandbox.organization_id, sandbox.principal_id, sandbox.party_id, scope),
        )


def _operator(factory: SessionFactory, sandbox) -> AsyncClient:
    app = create_operational_app(
        session_factory=factory,
        actor_resolver=SandboxResolver({sandbox.token: actor_for(sandbox)}),
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
@pytest.mark.e2e
@pytest.mark.postgres
@pytest.mark.contract
@pytest.mark.provenance
async def test_operator_supply_configuration_drives_customer_slot_and_booking(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = seed_tenant_sandbox(e2e_admin_conn, "operator-booking")
    _grant_operational_scopes(e2e_admin_conn, sandbox)
    location_revision = e2e_admin_conn.execute(
        "SELECT operational_revision FROM request_engine.locations WHERE id = %s",
        (sandbox.location_id,),
    ).fetchone()[0]
    resource_revision = e2e_admin_conn.execute(
        "SELECT availability_revision FROM request_engine.resources WHERE id = %s",
        (sandbox.resource_id,),
    ).fetchone()[0]

    async with _operator(e2e_session_factory, sandbox) as operator:
        hours = await operator.put(
            f"/v1/operations/locations/{sandbox.location_id}/hours",
            headers=auth(sandbox, idempotency_key=f"hours-{uuid4().hex}"),
            json={"authority_party_id": str(sandbox.party_id), "expected_operational_revision": location_revision,
                  "windows": [{"weekday": 0, "local_start": "08:00:00", "local_end": "17:00:00"}]},
        )
        assert hours.status_code == 200, hours.text
        assigned = await operator.post(
            "/v1/operations/resource-assignments",
            headers=auth(sandbox, idempotency_key=f"assign-{uuid4().hex}"),
            json={"authority_party_id": str(sandbox.party_id), "resource_id": str(sandbox.resource_id),
                  "location_id": str(sandbox.location_id), "effective_from": "2026-01-01T00:00:00Z",
                  "expected_resource_availability_revision": resource_revision},
        )
        assert assigned.status_code == 200, assigned.text
        assignment = assigned.json()
        availability = await operator.put(
            f"/v1/operations/resource-assignments/{assignment['assignment_id']}/availability",
            headers=auth(sandbox, idempotency_key=f"availability-{uuid4().hex}"),
            json={"authority_party_id": str(sandbox.party_id),
                  "expected_resource_availability_revision": assignment["resource_availability_revision"],
                  "windows": [{"weekday": 0, "local_start": "09:00:00", "local_end": "12:00:00"}]},
        )
        assert availability.status_code == 200, availability.text
        terms = await operator.post(
            "/v1/operations/context-terms",
            headers=auth(sandbox, idempotency_key=f"terms-{uuid4().hex}"),
            json={"authority_party_id": str(sandbox.party_id),
                  "resource_location_assignment_id": assignment["assignment_id"],
                  "offering_version_id": str(sandbox.offering_version_id), "effective_from": "2026-01-01T00:00:00Z",
                  "amount": "4000", "currency": "DOP", "planned_duration_minutes": 45, "bookable": True},
        )
        assert terms.status_code == 200, terms.text

    async with client_for(e2e_session_factory, sandbox) as customer:
        slot = await first_slot(customer, sandbox)
        assert slot["planned_duration_minutes"] == 45
        assert slot["amount"] == "4000.000000"
        booked = await customer.post(
            "/v1/appointments",
            headers=auth(sandbox, idempotency_key=f"book-{uuid4().hex}"),
            json={"option_id": slot["option_id"], "subject_party_id": str(sandbox.party_id)},
        )
    assert booked.status_code == 201, booked.text
    reservation_id = UUID(booked.json()["id"])
    claim = e2e_admin_conn.execute(
        "SELECT resource_location_assignment_id FROM request_engine.capacity_claims WHERE reservation_id = %s AND status = 'active'",
        (reservation_id,),
    ).fetchone()
    source = e2e_admin_conn.execute(
        "SELECT booking_context_terms_id FROM request_engine.reservation_commercial_commitment_context_terms WHERE reservation_id = %s",
        (reservation_id,),
    ).fetchone()
    assert claim == (UUID(assignment["assignment_id"]),)
    assert source == (UUID(terms.json()["context_terms_id"]),)
