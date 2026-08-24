from __future__ import annotations

import asyncio
from typing import Any, cast
from uuid import uuid4

import pytest
from httpx import AsyncClient, Response

from request_engine.platform.db.session import SessionFactory

from .contextual_supply_support import contextualize_sandbox
from .discovery_runtime_support import discovery_client
from .discovery_seed_support import create_classification, publish_sandbox, search_body
from .discovery_shared_capacity_support import bind_shared_root, create_shared_root
from .operational_support import PgConnection, RuntimeCredentialsLike
from .tenant_sandbox import TenantSandbox, auth, client_for, seed_tenant_sandbox


async def _book(client: AsyncClient, tenant: TenantSandbox, option_id: str) -> Response:
    return await client.post(
        "/v1/appointments",
        json={"option_id": option_id, "subject_party_id": str(tenant.party_id)},
        headers=auth(tenant, idempotency_key=f"f2-race-{uuid4().hex}"),
    )


@pytest.mark.asyncio
@pytest.mark.e2e
@pytest.mark.postgres
@pytest.mark.concurrency
@pytest.mark.security
@pytest.mark.capacity
async def test_discovery_shared_capacity_race_has_one_opaque_winner(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
    app_runtime_credentials: RuntimeCredentialsLike,
) -> None:
    tenant_a = seed_tenant_sandbox(e2e_admin_conn, "f2-shared-a")
    tenant_b = seed_tenant_sandbox(e2e_admin_conn, "f2-shared-b")
    contextualize_sandbox(e2e_admin_conn, tenant_a)
    contextualize_sandbox(e2e_admin_conn, tenant_b)
    root_id = create_shared_root(e2e_admin_conn)
    bind_shared_root(e2e_admin_conn, tenant_a, root_id)
    bind_shared_root(e2e_admin_conn, tenant_b, root_id)
    classification_id, key = create_classification(e2e_admin_conn)
    publish_sandbox(e2e_admin_conn, tenant_a, classification_id, latitude=19.8, longitude=-70.7)
    publish_sandbox(
        e2e_admin_conn, tenant_b, classification_id, latitude=19.8004, longitude=-70.7004
    )

    async with discovery_client(
        e2e_admin_conn, e2e_session_factory, app_runtime_credentials.database_url
    ) as discovery:
        search = await discovery.post("/v1/discovery/supply/search", json=search_body(key))
    assert search.status_code == 200, search.text
    options = cast(list[dict[str, Any]], search.json())
    selected = {item["organization_key"]: item for item in options}
    option_a = cast(str, selected[tenant_a.organization_key]["option_id"])
    option_b = cast(str, selected[tenant_b.organization_key]["option_id"])
    assert str(root_id) not in search.text
    assert "organization_id" not in search.text

    async with (
        client_for(e2e_session_factory, tenant_a) as client_a,
        client_for(e2e_session_factory, tenant_b) as client_b,
    ):
        result_a, result_b = await asyncio.gather(
            _book(client_a, tenant_a, option_a),
            _book(client_b, tenant_b, option_b),
        )
    assert sorted((result_a.status_code, result_b.status_code)) == [201, 409]
    loser = result_a if result_a.status_code == 409 else result_b
    assert str(root_id) not in loser.text
    assert "shared_capacity" not in loser.text.lower()

    reservations = e2e_admin_conn.execute(
        "SELECT count(*) FROM request_engine.reservations WHERE organization_id IN (%s, %s)",
        (tenant_a.organization_id, tenant_b.organization_id),
    ).fetchone()
    assert reservations == (1,)
    links = e2e_admin_conn.execute(
        "SELECT count(*) FROM request_engine.shared_capacity_claim_links "
        "WHERE shared_capacity_identity_id = %s",
        (root_id,),
    ).fetchone()
    assert links == (1,)
