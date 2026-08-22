from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from request_engine.entrypoints.http.operational_app import create_operational_app
from request_engine.platform.db.session import SessionFactory

from .operational_support import PgConnection
from .tenant_sandbox import (
    SandboxResolver,
    TenantSandbox,
    actor_for,
    auth,
    seed_tenant_sandbox,
)


def _grant(conn: PgConnection, sandbox: TenantSandbox) -> None:
    conn.execute(
        """
        INSERT INTO request_engine.representations (
            organization_id, principal_id, represented_party_id,
            authority_kind, scope_key, valid_until
        ) VALUES (
            %s, %s, %s, 'delegated', 'operations.manage_profile',
            clock_timestamp() + interval '1 day'
        )
        """,
        (sandbox.organization_id, sandbox.principal_id, sandbox.party_id),
    )


def _client(factory: SessionFactory, sandbox: TenantSandbox) -> AsyncClient:
    resolver = SandboxResolver({sandbox.token: actor_for(sandbox)})
    app = create_operational_app(session_factory=factory, actor_resolver=resolver)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
@pytest.mark.e2e
@pytest.mark.postgres
@pytest.mark.security
async def test_foreign_location_is_as_opaque_as_unknown_location_and_is_not_mutated(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    actor_tenant = seed_tenant_sandbox(e2e_admin_conn, "ops-owner")
    foreign = seed_tenant_sandbox(e2e_admin_conn, "ops-foreign")
    _grant(e2e_admin_conn, actor_tenant)
    before = e2e_admin_conn.execute(
        "SELECT timezone, operational_revision FROM request_engine.locations WHERE id = %s",
        (foreign.location_id,),
    ).fetchone()
    body = {
        "authority_party_id": str(actor_tenant.party_id),
        "timezone": "America/New_York",
        "active": True,
        "expected_operational_revision": 1,
    }

    async with _client(e2e_session_factory, actor_tenant) as client:
        foreign_response = await client.patch(
            f"/v1/operations/locations/{foreign.location_id}",
            headers=auth(actor_tenant, idempotency_key=f"foreign-{uuid4().hex}"),
            json=body,
        )
        unknown_response = await client.patch(
            f"/v1/operations/locations/{uuid4()}",
            headers=auth(actor_tenant, idempotency_key=f"unknown-{uuid4().hex}"),
            json=body,
        )

    assert foreign_response.status_code == 409
    assert unknown_response.status_code == 409
    assert foreign_response.json()["error"] == unknown_response.json()["error"]
    after = e2e_admin_conn.execute(
        "SELECT timezone, operational_revision FROM request_engine.locations WHERE id = %s",
        (foreign.location_id,),
    ).fetchone()
    assert after == before
