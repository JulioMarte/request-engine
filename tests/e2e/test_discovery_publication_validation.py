from datetime import UTC, datetime
from uuid import uuid4

import pytest

from request_engine.platform.db.session import SessionFactory

from .discovery_operational_support import grant_manage_discovery, operational_client
from .operational_support import PgConnection
from .tenant_sandbox import auth, seed_tenant_sandbox


@pytest.mark.asyncio
@pytest.mark.e2e
@pytest.mark.postgres
@pytest.mark.contract
@pytest.mark.adversarial
async def test_public_provider_publication_without_resource_is_validation_error_and_non_mutating(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    tenant = seed_tenant_sandbox(e2e_admin_conn, "f2-publication-validation")
    grant_manage_discovery(e2e_admin_conn, tenant)
    before = e2e_admin_conn.execute(
        "SELECT count(*) FROM request_engine.discovery_publications WHERE organization_id=%s",
        (tenant.organization_id,),
    ).fetchone()

    async with operational_client(e2e_session_factory, tenant) as client:
        response = await client.post(
            "/v1/operations/discovery/publications",
            headers=auth(tenant, idempotency_key=f"f2-invalid-publication-{uuid4().hex}"),
            json={
                "authority_party_id": str(tenant.party_id),
                "offering_id": str(tenant.offering_id),
                "location_id": str(tenant.location_id),
                "resource_id": None,
                "effective_start": datetime(2030, 1, 1, tzinfo=UTC).isoformat(),
                "effective_end": datetime(2031, 1, 1, tzinfo=UTC).isoformat(),
                "provider_visibility": "public",
            },
        )

    assert response.status_code == 422, response.text
    assert "public provider visibility requires resource_id" in response.text
    after = e2e_admin_conn.execute(
        "SELECT count(*) FROM request_engine.discovery_publications WHERE organization_id=%s",
        (tenant.organization_id,),
    ).fetchone()
    assert after == before
