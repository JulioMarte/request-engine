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


def _client(factory: SessionFactory, sandbox: TenantSandbox) -> AsyncClient:
    resolver = SandboxResolver({sandbox.token: actor_for(sandbox)})
    app = create_operational_app(session_factory=factory, actor_resolver=resolver)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _insert_representation(
    conn: PgConnection,
    sandbox: TenantSandbox,
    *,
    scope_key: str,
    validity: str,
) -> None:
    conn.execute(
        """
        INSERT INTO request_engine.representations (
            organization_id, principal_id, represented_party_id,
            authority_kind, scope_key, valid_until
        ) VALUES (%s, %s, %s, 'delegated', %s, clock_timestamp() + %s::interval)
        """,
        (
            sandbox.organization_id,
            sandbox.principal_id,
            sandbox.party_id,
            scope_key,
            validity,
        ),
    )


@pytest.mark.asyncio
@pytest.mark.e2e
@pytest.mark.postgres
@pytest.mark.security
@pytest.mark.parametrize(
    ("scope_key", "validity"),
    [("operations.manage_schedule", "1 day"), ("operations.manage_profile", "-1 day")],
)
async def test_wrong_scope_and_expired_authority_fail_closed_without_mutation(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
    scope_key: str,
    validity: str,
) -> None:
    sandbox = seed_tenant_sandbox(e2e_admin_conn, f"ops-authority-{uuid4().hex[:6]}")
    _insert_representation(
        e2e_admin_conn,
        sandbox,
        scope_key=scope_key,
        validity=validity,
    )
    before = e2e_admin_conn.execute(
        "SELECT legal_name FROM request_engine.organizations WHERE id = %s",
        (sandbox.organization_id,),
    ).fetchone()

    async with _client(e2e_session_factory, sandbox) as client:
        response = await client.patch(
            "/v1/operations/organization/profile",
            headers=auth(sandbox, idempotency_key=f"authority-{uuid4().hex}"),
            json={"authority_party_id": str(sandbox.party_id), "legal_name": "Forbidden"},
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "operational_authority_required"
    after = e2e_admin_conn.execute(
        "SELECT legal_name FROM request_engine.organizations WHERE id = %s",
        (sandbox.organization_id,),
    ).fetchone()
    assert after == before
