from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from request_engine.platform.db.session import SessionFactory

from .contextual_resource_support import add_contextual_resource
from .contextual_supply_support import contextualize_sandbox
from .operational_support import PgConnection
from .tenant_sandbox import auth, client_for, seed_tenant_sandbox


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
    preferred_id = add_contextual_resource(
        e2e_admin_conn,
        sandbox,
        amount=4500,
        duration_minutes=30,
    )
    foreign = seed_tenant_sandbox(e2e_admin_conn, "resource-preference-foreign")
    params = {
        "offering_version_id": str(sandbox.offering_version_id),
        "location_id": str(sandbox.location_id),
        "window_start": datetime(2030, 1, 7, 13, 0, tzinfo=UTC).isoformat(),
        "window_end": datetime(2030, 1, 7, 16, 0, tzinfo=UTC).isoformat(),
        "limit": 200,
    }
    async with client_for(e2e_session_factory, sandbox, foreign) as client:
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
        foreign_response = await client.get(
            "/v1/appointments/slots",
            params={**params, "resource_id": str(foreign.resource_id)},
            headers=auth(sandbox),
        )
    assert any_response.status_code == 200
    assert pinned_response.status_code == 200
    assert unknown_response.status_code == 200
    assert foreign_response.status_code == 200
    any_ids = {
        choice["resource_id"] for slot in any_response.json() for choice in slot["resources"]
    }
    assert {str(sandbox.resource_id), str(preferred_id)} <= any_ids
    pinned = pinned_response.json()
    assert pinned
    pinned_ids = {choice["resource_id"] for slot in pinned for choice in slot["resources"]}
    assert pinned_ids == {str(preferred_id)}
    assert {Decimal(str(slot["amount"])) for slot in pinned} == {Decimal("4500")}
    assert unknown_response.json() == []
    assert foreign_response.json() == []
