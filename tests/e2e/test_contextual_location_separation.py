from __future__ import annotations

from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from request_engine.platform.db.session import SessionFactory

from .contextual_supply_support import contextualize_sandbox
from .operational_support import PgConnection
from .tenant_sandbox import TenantSandbox, auth, client_for, first_slot, seed_tenant_sandbox


def _second_context(conn: PgConnection, sandbox: TenantSandbox) -> UUID:
    suffix = uuid4().hex
    row = conn.execute(
        """
        INSERT INTO request_engine.locations (
            organization_id, location_key, display_name, timezone
        ) VALUES (%s, %s, 'Second clinic', 'America/Santo_Domingo')
        RETURNING id
        """,
        (sandbox.organization_id, f"second-{suffix}"),
    ).fetchone()
    assert row is not None
    location_id = cast(UUID, row[0])
    conn.execute(
        "INSERT INTO request_engine.location_operational_hours "
        "(organization_id, location_id, weekday, local_start, local_end) "
        "VALUES (%s, %s, 0, '08:00', '17:00')",
        (sandbox.organization_id, location_id),
    )
    row = conn.execute(
        """
        INSERT INTO request_engine.resource_location_assignments (
            organization_id, resource_id, location_id, effective_during
        ) VALUES (%s, %s, %s,
            tstzrange('2026-01-01T00:00:00+00'::timestamptz, NULL, '[)'))
        RETURNING id
        """,
        (sandbox.organization_id, sandbox.resource_id, location_id),
    ).fetchone()
    assert row is not None
    assignment_id = cast(UUID, row[0])
    conn.execute(
        "INSERT INTO request_engine.resource_location_availability "
        "(organization_id, resource_location_assignment_id, weekday, local_start, local_end) "
        "VALUES (%s, %s, 0, '10:00', '12:00')",
        (sandbox.organization_id, assignment_id),
    )
    conn.execute(
        """
        INSERT INTO request_engine.booking_context_terms (
            organization_id, resource_location_assignment_id, offering_version_id,
            effective_during, amount, currency, planned_duration_minutes
        ) VALUES (%s, %s, %s,
            tstzrange('2026-01-01T00:00:00+00'::timestamptz, NULL, '[)'),
            5200, 'DOP', 30)
        """,
        (sandbox.organization_id, assignment_id, sandbox.offering_version_id),
    )
    return location_id


async def _slots(
    client: AsyncClient,
    sandbox: TenantSandbox,
    location_id: UUID,
) -> list[dict[str, Any]]:
    response = await client.get(
        "/v1/appointments/slots",
        params={
            "offering_version_id": str(sandbox.offering_version_id),
            "location_id": str(location_id),
            "window_start": "2030-01-07T13:00:00+00:00",
            "window_end": "2030-01-07T16:00:00+00:00",
        },
        headers=auth(sandbox),
    )
    assert response.status_code == 200, response.text
    return cast(list[dict[str, Any]], response.json())


@pytest.mark.asyncio
@pytest.mark.e2e
@pytest.mark.postgres
@pytest.mark.contract
@pytest.mark.temporal
async def test_same_resource_keeps_location_schedule_and_terms_separate(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = seed_tenant_sandbox(e2e_admin_conn, "multi-location-e2e")
    contextualize_sandbox(e2e_admin_conn, sandbox)
    second_location_id = _second_context(e2e_admin_conn, sandbox)

    async with client_for(e2e_session_factory, sandbox) as client:
        first = await first_slot(client, sandbox)
        second_slots = await _slots(client, sandbox, second_location_id)

    assert first["location_id"] == str(sandbox.location_id)
    assert first["start_at"] == "2030-01-07T13:00:00Z"
    assert first["planned_duration_minutes"] == 45
    assert Decimal(str(first["amount"])) == Decimal("4000")

    assert second_slots
    second = second_slots[0]
    assert second["location_id"] == str(second_location_id)
    assert second["start_at"] == "2030-01-07T14:00:00Z"
    assert second["planned_duration_minutes"] == 30
    assert Decimal(str(second["amount"])) == Decimal("5200")
