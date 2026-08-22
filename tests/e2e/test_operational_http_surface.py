from uuid import UUID, uuid4

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


def _grant(
    conn: PgConnection,
    *,
    organization_id: UUID,
    principal_id: UUID,
    authority_party_id: UUID,
    scope_key: str,
) -> None:
    conn.execute(
        """
        INSERT INTO request_engine.representations (
            organization_id, principal_id, represented_party_id,
            authority_kind, scope_key, valid_until
        ) VALUES (%s, %s, %s, 'delegated', %s, clock_timestamp() + interval '1 day')
        """,
        (organization_id, principal_id, authority_party_id, scope_key),
    )


def _client(session_factory: SessionFactory, sandbox: TenantSandbox) -> AsyncClient:
    resolver = SandboxResolver({sandbox.token: actor_for(sandbox)})
    app = create_operational_app(session_factory=session_factory, actor_resolver=resolver)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
@pytest.mark.e2e
@pytest.mark.postgres
async def test_operational_http_requires_representation_and_maps_input_errors_without_effects(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = seed_tenant_sandbox(e2e_admin_conn, "ops-http")
    before = e2e_admin_conn.execute(
        "SELECT legal_name FROM request_engine.organizations WHERE id = %s",
        (sandbox.organization_id,),
    ).fetchone()
    async with _client(e2e_session_factory, sandbox) as client:
        denied = await client.patch(
            "/v1/operations/organization/profile",
            headers=auth(sandbox, idempotency_key=f"ops-denied-{uuid4().hex}"),
            json={"authority_party_id": str(sandbox.party_id), "legal_name": "Denied"},
        )
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "operational_authority_required"

        _grant(
            e2e_admin_conn,
            organization_id=sandbox.organization_id,
            principal_id=sandbox.principal_id,
            authority_party_id=sandbox.party_id,
            scope_key="operations.manage_profile",
        )
        invalid = await client.put(
            "/v1/operations/organization/contacts",
            headers=auth(sandbox, idempotency_key=f"ops-contact-{uuid4().hex}"),
            json={
                "authority_party_id": str(sandbox.party_id),
                "contacts": [{"channel": "phone", "value": "809-555-0199"}],
            },
        )
        assert invalid.status_code == 422
        assert invalid.json()["error"]["code"] == "public_contact_invalid"

    after = e2e_admin_conn.execute(
        "SELECT legal_name FROM request_engine.organizations WHERE id = %s",
        (sandbox.organization_id,),
    ).fetchone()
    contacts = e2e_admin_conn.execute(
        "SELECT count(*) FROM request_engine.organization_public_contact_endpoints WHERE organization_id = %s",
        (sandbox.organization_id,),
    ).fetchone()
    assert after == before
    assert contacts == (0,)
