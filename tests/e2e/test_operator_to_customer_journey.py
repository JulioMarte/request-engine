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
    client_for,
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


def _operator(factory: SessionFactory, sandbox: TenantSandbox) -> AsyncClient:
    resolver = SandboxResolver({sandbox.token: actor_for(sandbox)})
    app = create_operational_app(session_factory=factory, actor_resolver=resolver)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
@pytest.mark.e2e
@pytest.mark.postgres
async def test_operator_configuration_becomes_customer_visible_through_public_api(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = seed_tenant_sandbox(e2e_admin_conn, "ops-customer")
    _grant(e2e_admin_conn, sandbox)

    async with _operator(e2e_session_factory, sandbox) as operator:
        profile = await operator.patch(
            "/v1/operations/organization/profile",
            headers=auth(sandbox, idempotency_key=f"profile-{uuid4().hex}"),
            json={
                "authority_party_id": str(sandbox.party_id),
                "legal_name": "Configured Clinic SRL",
                "default_timezone": "America/Santo_Domingo",
                "default_locale": "es-DO",
                "default_currency": "DOP",
                "operational_status": "active",
            },
        )
        contacts = await operator.put(
            "/v1/operations/organization/contacts",
            headers=auth(sandbox, idempotency_key=f"contacts-{uuid4().hex}"),
            json={
                "authority_party_id": str(sandbox.party_id),
                "contacts": [
                    {"channel": "phone", "value": "+18095550199", "label": "Central"},
                    {"channel": "email", "value": "Info@Example.TEST", "label": "Info"},
                ],
            },
        )
    assert profile.status_code == 200, profile.text
    assert contacts.status_code == 200, contacts.text

    async with client_for(e2e_session_factory, sandbox) as customer:
        response = await customer.get("/v1/business", headers=auth(sandbox))
    assert response.status_code == 200, response.text
    business = response.json()
    assert business["legal_name"] == "Configured Clinic SRL"
    assert business["default_timezone"] == "America/Santo_Domingo"
    assert business["default_locale"] == "es-DO"
    assert business["default_currency"] == "DOP"
    values = {(item["channel"], item["value"]) for item in business["contacts"]}
    assert ("phone", "+18095550199") in values
    assert ("email", "info@example.test") in values
