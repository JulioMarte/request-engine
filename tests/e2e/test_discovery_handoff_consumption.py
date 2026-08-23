from typing import Any, cast
from uuid import uuid4

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
@pytest.mark.adversarial
async def test_consumed_discoopt_replays_same_request_but_rejects_new_mutation(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
    app_runtime_credentials: RuntimeCredentialsLike,
) -> None:
    tenant = seed_tenant_sandbox(e2e_admin_conn, "f2-consumed")
    contextualize_sandbox(e2e_admin_conn, tenant)
    classification_id, key = create_classification(e2e_admin_conn)
    publish_sandbox(e2e_admin_conn, tenant, classification_id, latitude=19.8, longitude=-70.7)
    async with discovery_client(
        e2e_admin_conn, e2e_session_factory, app_runtime_credentials.database_url
    ) as discovery:
        found = await discovery.post("/v1/discovery/supply/search", json=search_body(key))
    assert found.status_code == 200, found.text
    option_id = cast(str, cast(list[dict[str, Any]], found.json())[0]["option_id"])
    payload = {"option_id": option_id, "subject_party_id": str(tenant.party_id)}
    same_key = f"f2-consumed-{uuid4().hex}"

    async with client_for(e2e_session_factory, tenant) as booking:
        first = await booking.post(
            "/v1/appointments", headers=auth(tenant, idempotency_key=same_key), json=payload
        )
        replay = await booking.post(
            "/v1/appointments", headers=auth(tenant, idempotency_key=same_key), json=payload
        )
        second = await booking.post(
            "/v1/appointments",
            headers=auth(tenant, idempotency_key=f"f2-new-{uuid4().hex}"),
            json=payload,
        )

    assert first.status_code == 201, first.text
    assert replay.status_code == 201 and replay.json() == first.json()
    assert second.status_code in {409, 422}, second.text
    assert e2e_admin_conn.execute(
        "SELECT count(*) FROM request_engine.reservations WHERE organization_id=%s",
        (tenant.organization_id,),
    ).fetchone() == (1,)
    assert e2e_admin_conn.execute(
        "SELECT count(*) FROM request_engine.capacity_claims WHERE organization_id=%s",
        (tenant.organization_id,),
    ).fetchone() == (1,)
