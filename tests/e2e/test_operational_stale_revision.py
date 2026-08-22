from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from request_engine.entrypoints.http.operational_app import create_operational_app
from request_engine.platform.db.session import SessionFactory

from .operational_support import PgConnection
from .tenant_sandbox import SandboxResolver, TenantSandbox, actor_for, auth, seed_tenant_sandbox


def _grant(conn: PgConnection, sandbox: TenantSandbox) -> None:
    conn.execute(
        """
        INSERT INTO request_engine.representations (
            organization_id, principal_id, represented_party_id,
            authority_kind, scope_key, valid_until
        ) VALUES (%s, %s, %s, 'delegated', 'operations.manage_profile', clock_timestamp() + interval '1 day')
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
async def test_stale_location_revision_is_conflict_without_partial_write(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = seed_tenant_sandbox(e2e_admin_conn, "ops-stale")
    _grant(e2e_admin_conn, sandbox)
    before = e2e_admin_conn.execute(
        "SELECT timezone, operational_revision FROM request_engine.locations WHERE id = %s",
        (sandbox.location_id,),
    ).fetchone()
    async with _client(e2e_session_factory, sandbox) as client:
        response = await client.patch(
            f"/v1/operations/locations/{sandbox.location_id}",
            headers=auth(sandbox, idempotency_key=f"ops-stale-{uuid4().hex}"),
            json={
                "authority_party_id": str(sandbox.party_id),
                "timezone": "America/New_York",
                "active": True,
                "expected_operational_revision": 999999,
            },
        )
    assert response.status_code == 409
    body = response.json()["error"]
    assert body["code"] == "location_operational_revision_conflict"
    assert body["resolution"] == "refresh_and_retry"
    after = e2e_admin_conn.execute(
        "SELECT timezone, operational_revision FROM request_engine.locations WHERE id = %s",
        (sandbox.location_id,),
    ).fetchone()
    assert after == before
