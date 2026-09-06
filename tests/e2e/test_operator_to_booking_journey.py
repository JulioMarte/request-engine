from typing import cast
from uuid import UUID, uuid4

import pytest

from request_engine.platform.db.session import SessionFactory

from .operational_support import PgConnection
from .operator_journey_support import grant_operational_scopes, operator_client, revision
from .tenant_sandbox import auth, client_for, first_slot, seed_tenant_sandbox


def _remove_baseline_supply(conn: PgConnection, organization_id: UUID) -> None:
    conn.execute(
        "DELETE FROM request_engine.resource_location_availability WHERE organization_id = %s",
        (organization_id,),
    )
    conn.execute(
        "DELETE FROM request_engine.resource_location_assignments WHERE organization_id = %s",
        (organization_id,),
    )
    conn.execute(
        "DELETE FROM request_engine.location_operational_hours WHERE organization_id = %s",
        (organization_id,),
    )


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
    _remove_baseline_supply(e2e_admin_conn, sandbox.organization_id)
    grant_operational_scopes(e2e_admin_conn, sandbox)
    location_revision = revision(
        e2e_admin_conn,
        "SELECT operational_revision FROM request_engine.locations WHERE id = %s",
        sandbox.location_id,
    )
    resource_revision = revision(
        e2e_admin_conn,
        "SELECT availability_revision FROM request_engine.resources WHERE id = %s",
        sandbox.resource_id,
    )

    async with operator_client(e2e_session_factory, sandbox) as operator:
        hours = await operator.put(
            f"/v1/operations/locations/{sandbox.location_id}/hours",
            headers=auth(sandbox, idempotency_key=f"hours-{uuid4().hex}"),
            json={
                "authority_party_id": str(sandbox.party_id),
                "expected_operational_revision": location_revision,
                "windows": [{"weekday": 0, "local_start": "08:00:00", "local_end": "17:00:00"}],
            },
        )
        assert hours.status_code == 200, hours.text
        assigned = await operator.post(
            "/v1/operations/resource-assignments",
            headers=auth(sandbox, idempotency_key=f"assign-{uuid4().hex}"),
            json={
                "authority_party_id": str(sandbox.party_id),
                "resource_id": str(sandbox.resource_id),
                "location_id": str(sandbox.location_id),
                "effective_from": "2026-01-01T00:00:00Z",
                "expected_resource_availability_revision": resource_revision,
            },
        )
        assert assigned.status_code == 200, assigned.text
        assignment = cast(dict[str, object], assigned.json())
        assignment_id = str(assignment["assignment_id"])
        availability = await operator.put(
            f"/v1/operations/resource-assignments/{assignment_id}/availability",
            headers=auth(sandbox, idempotency_key=f"availability-{uuid4().hex}"),
            json={
                "authority_party_id": str(sandbox.party_id),
                "expected_resource_availability_revision": assignment[
                    "resource_availability_revision"
                ],
                "windows": [{"weekday": 0, "local_start": "09:00:00", "local_end": "12:00:00"}],
            },
        )
        assert availability.status_code == 200, availability.text
        terms = await operator.post(
            "/v1/operations/context-terms",
            headers=auth(sandbox, idempotency_key=f"terms-{uuid4().hex}"),
            json={
                "authority_party_id": str(sandbox.party_id),
                "resource_location_assignment_id": assignment_id,
                "offering_version_id": str(sandbox.offering_version_id),
                "effective_from": "2026-01-01T00:00:00Z",
                "amount": "4000",
                "currency": "DOP",
                "planned_duration_minutes": 45,
                "bookable": True,
            },
        )
        assert terms.status_code == 200, terms.text

    async with client_for(e2e_session_factory, sandbox) as customer:
        slot = await first_slot(customer, sandbox)
        assert slot["planned_duration_minutes"] == 45
        booked = await customer.post(
            "/v1/appointments",
            headers=auth(sandbox, idempotency_key=f"book-{uuid4().hex}"),
            json={"option_id": slot["option_id"], "subject_party_id": str(sandbox.party_id)},
        )
    assert booked.status_code == 201, booked.text
    reservation_id = UUID(booked.json()["id"])
    claim = e2e_admin_conn.execute(
        "SELECT resource_location_assignment_id FROM request_engine.capacity_claims "
        "WHERE reservation_id = %s AND status = 'active'",
        (reservation_id,),
    ).fetchone()
    terms_body = cast(dict[str, object], terms.json())
    source = e2e_admin_conn.execute(
        "SELECT booking_context_terms_id FROM "
        "request_engine.reservation_commercial_commitment_context_terms "
        "WHERE reservation_id = %s",
        (reservation_id,),
    ).fetchone()
    assert claim == (UUID(assignment_id),)
    assert source == (UUID(str(terms_body["context_terms_id"])),)
