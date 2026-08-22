from uuid import uuid4

import pytest

from request_engine.platform.db.session import SessionFactory

from .evidence import durable_snapshot
from .operational_support import PgConnection
from .operator_journey_support import operator_client
from .tenant_sandbox import TenantSandbox, auth, seed_tenant_sandbox


def _grant_profile_only(conn: PgConnection, sandbox: TenantSandbox) -> None:
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


@pytest.mark.asyncio
@pytest.mark.e2e
@pytest.mark.postgres
@pytest.mark.security
async def test_profile_authority_cannot_mutate_supply_or_commercial_terms(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = seed_tenant_sandbox(e2e_admin_conn, "ops-scope-boundary")
    _grant_profile_only(e2e_admin_conn, sandbox)
    resource_revision = e2e_admin_conn.execute(
        "SELECT availability_revision FROM request_engine.resources WHERE id = %s",
        (sandbox.resource_id,),
    ).fetchone()
    assert resource_revision is not None
    before = durable_snapshot(e2e_admin_conn)

    async with operator_client(e2e_session_factory, sandbox) as client:
        supply = await client.post(
            "/v1/operations/resource-assignments",
            headers=auth(sandbox, idempotency_key=f"scope-supply-{uuid4().hex}"),
            json={
                "authority_party_id": str(sandbox.party_id),
                "resource_id": str(sandbox.resource_id),
                "location_id": str(sandbox.location_id),
                "effective_from": "2026-01-01T00:00:00Z",
                "expected_resource_availability_revision": resource_revision[0],
            },
        )
        terms = await client.put(
            f"/v1/operations/offering-versions/{sandbox.offering_version_id}/booking-terms",
            headers=auth(sandbox, idempotency_key=f"scope-terms-{uuid4().hex}"),
            json={
                "authority_party_id": str(sandbox.party_id),
                "amount": "2500",
                "currency": "DOP",
            },
        )

    assert supply.status_code == 403
    assert terms.status_code == 403
    assert supply.json()["error"]["code"] == "operational_authority_required"
    assert terms.json()["error"]["code"] == "operational_authority_required"
    assert durable_snapshot(e2e_admin_conn) == before
