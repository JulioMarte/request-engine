from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from request_engine.platform.db.session import SessionFactory

from .contextual_supply_support import contextualize_sandbox
from .operational_support import PgConnection
from .tenant_sandbox import auth, client_for, seed_tenant_sandbox


def _second_resource(
    conn: PgConnection,
    organization_id: UUID,
    requirement_id: UUID,
    location_id: UUID,
    offering_version_id: UUID,
) -> UUID:
    capability = conn.execute(
        "SELECT capability_id FROM request_engine.offering_resource_requirements "
        "WHERE organization_id = %s AND id = %s",
        (organization_id, requirement_id),
    ).fetchone()
    assert capability is not None
    resource = conn.execute(
        """
        INSERT INTO request_engine.resources (
            organization_id, location_id, resource_key, display_name,
            capacity_model, capacity_units
        ) VALUES (%s, %s, %s, 'Preferred doctor', 'exclusive', 1)
        RETURNING id
        """,
        (organization_id, location_id, f"preferred-{uuid4().hex}"),
    ).fetchone()
    assert resource is not None
    resource_id = UUID(str(resource[0]))
    conn.execute(
        """
        INSERT INTO request_engine.resource_capability_assignments (
            organization_id, resource_id, capability_id
        ) VALUES (%s, %s, %s)
        """,
        (organization_id, resource_id, capability[0]),
    )
    assignment = conn.execute(
        """
        INSERT INTO request_engine.resource_location_assignments (
            organization_id, resource_id, location_id, effective_during
        ) VALUES (
            %s, %s, %s,
            tstzrange('2026-01-01T00:00:00+00', NULL, '[)')
        )
        RETURNING id
        """,
        (organization_id, resource_id, location_id),
    ).fetchone()
    assert assignment is not None
    conn.execute(
        """
        INSERT INTO request_engine.resource_location_availability (
            organization_id, resource_location_assignment_id,
            weekday, local_start, local_end
        ) VALUES (%s, %s, 0, '09:00', '12:00')
        """,
        (organization_id, assignment[0]),
    )
    conn.execute(
        """
        INSERT INTO request_engine.booking_context_terms (
            organization_id, resource_location_assignment_id, offering_version_id,
            effective_during, amount, currency, planned_duration_minutes
        ) VALUES (
            %s, %s, %s,
            tstzrange('2026-01-01T00:00:00+00', NULL, '[)'),
            4500, 'DOP', 30
        )
        """,
        (organization_id, assignment[0], offering_version_id),
    )
    return resource_id


@pytest.mark.asyncio
@pytest.mark.e2e
@pytest.mark.postgres
@pytest.mark.contract
@pytest.mark.adversarial
async def test_find_slots_can_pin_one_eligible_resource_without_leaking_unknown_ids(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = seed_tenant_sandbox(e2e_admin_conn, "resource-preference-e2e")
    contextualize_sandbox(e2e_admin_conn, sandbox)
    preferred_id = _second_resource(
        e2e_admin_conn,
        sandbox.organization_id,
        sandbox.requirement_id,
        sandbox.location_id,
        sandbox.offering_version_id,
    )
    params = {
        "offering_version_id": str(sandbox.offering_version_id),
        "location_id": str(sandbox.location_id),
        "window_start": datetime(2030, 1, 7, 13, 0, tzinfo=UTC).isoformat(),
        "window_end": datetime(2030, 1, 7, 16, 0, tzinfo=UTC).isoformat(),
        "limit": 200,
    }
    async with client_for(e2e_session_factory, sandbox) as client:
        any_response = await client.get(
            "/v1/appointments/slots", params=params, headers=auth(sandbox)
        )
        pinned_response = await client.get(
            "/v1/appointments/slots",
            params={**params, "resource_id": str(preferred_id)},
            headers=auth(sandbox),
        )
        unknown_response = await client.get(
            "/v1/appointments/slots",
            params={**params, "resource_id": str(uuid4())},
            headers=auth(sandbox),
        )
    assert any_response.status_code == 200
    assert pinned_response.status_code == 200
    assert unknown_response.status_code == 200
    any_ids = {
        choice["resource_id"]
        for slot in any_response.json()
        for choice in slot["resources"]
    }
    assert {str(sandbox.resource_id), str(preferred_id)} <= any_ids
    pinned = pinned_response.json()
    assert pinned
    pinned_ids = {
        choice["resource_id"] for slot in pinned for choice in slot["resources"]
    }
    assert pinned_ids == {str(preferred_id)}
    assert {Decimal(str(slot["amount"])) for slot in pinned} == {Decimal("4500")}
    assert unknown_response.json() == []
