from uuid import uuid4

import pytest

from request_engine.platform.db.session import SessionFactory

from .discovery_operational_support import grant_manage_discovery, operational_client
from .operational_support import PgConnection
from .tenant_sandbox import auth, seed_tenant_sandbox


@pytest.mark.asyncio
@pytest.mark.e2e
@pytest.mark.postgres
@pytest.mark.security
async def test_resource_public_profile_is_authorized_idempotent_and_audited(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    tenant = seed_tenant_sandbox(e2e_admin_conn, "f2-provider-profile")
    grant_manage_discovery(e2e_admin_conn, tenant)
    key = f"f2-provider-profile-{uuid4().hex}"
    body = {
        "authority_party_id": str(tenant.party_id),
        "display_name": "Dr. A",
        "role_label": "Cardiologist",
        "profile_image_ref": "https://cdn.example.test/dr-a.jpg",
    }
    async with operational_client(e2e_session_factory, tenant) as client:
        first = await client.put(
            f"/v1/operations/discovery/resources/{tenant.resource_id}/public-profile",
            headers=auth(tenant, idempotency_key=key),
            json=body,
        )
        replay = await client.put(
            f"/v1/operations/discovery/resources/{tenant.resource_id}/public-profile",
            headers=auth(tenant, idempotency_key=key),
            json=body,
        )
    assert first.status_code == 200, first.text
    assert replay.status_code == 200 and replay.json() == first.json()
    assert first.json()["display_name"] == "Dr. A"
    assert first.json()["revision"] == 1
    assert e2e_admin_conn.execute(
        "SELECT display_name, role_label, revision FROM request_engine.resource_public_profiles "
        "WHERE organization_id=%s AND resource_id=%s",
        (tenant.organization_id, tenant.resource_id),
    ).fetchone() == ("Dr. A", "Cardiologist", 1)
    assert e2e_admin_conn.execute(
        "SELECT count(*) FROM request_engine.audit_records WHERE organization_id=%s "
        "AND command_name='discovery.set_resource_public_profile'",
        (tenant.organization_id,),
    ).fetchone() == (1,)
