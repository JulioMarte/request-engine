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
async def test_operator_profile_replay_is_single_effect_and_conflicting_replay_is_rejected(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = seed_tenant_sandbox(e2e_admin_conn, "ops-replay")
    _grant(e2e_admin_conn, sandbox)
    key = f"ops-profile-{uuid4().hex}"
    body = {
        "authority_party_id": str(sandbox.party_id),
        "legal_name": "Replay Clinic",
        "default_timezone": "America/Santo_Domingo",
        "default_locale": "es-DO",
        "default_currency": "DOP",
        "operational_status": "active",
    }

    async with _client(e2e_session_factory, sandbox) as client:
        first = await client.patch(
            "/v1/operations/organization/profile",
            headers=auth(sandbox, idempotency_key=key),
            json=body,
        )
        replay = await client.patch(
            "/v1/operations/organization/profile",
            headers=auth(sandbox, idempotency_key=key),
            json=body,
        )
        conflicting = await client.patch(
            "/v1/operations/organization/profile",
            headers=auth(sandbox, idempotency_key=key),
            json={**body, "legal_name": "Must Not Persist"},
        )

    assert first.status_code == 200, first.text
    assert replay.status_code == 200, replay.text
    assert replay.json() == first.json()
    assert conflicting.status_code == 409, conflicting.text

    row = e2e_admin_conn.execute(
        "SELECT legal_name, default_currency FROM request_engine.organizations WHERE id = %s",
        (sandbox.organization_id,),
    ).fetchone()
    assert row == ("Replay Clinic", "DOP")
    audit_count = e2e_admin_conn.execute(
        """
        SELECT count(*) FROM request_engine.audit_records
        WHERE organization_id = %s
          AND command_name = 'tenancy.update_organization_operational_profile'
        """,
        (sandbox.organization_id,),
    ).fetchone()
    assert audit_count == (1,)
