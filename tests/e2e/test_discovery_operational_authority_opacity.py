from uuid import uuid4

import pytest

from request_engine.platform.db.session import SessionFactory

from .discovery_operational_support import (
    create_classification,
    grant_manage_discovery,
    operational_client,
)
from .operational_support import PgConnection
from .tenant_sandbox import auth, seed_tenant_sandbox


@pytest.mark.asyncio
@pytest.mark.e2e
@pytest.mark.postgres
@pytest.mark.security
@pytest.mark.adversarial
async def test_discovery_mapping_requires_manage_discovery_and_leaves_no_partial_state(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = seed_tenant_sandbox(e2e_admin_conn, "f2-map-authority")
    classification = create_classification(e2e_admin_conn)
    async with operational_client(e2e_session_factory, sandbox) as client:
        response = await client.put(
            f"/v1/operations/discovery/offerings/{sandbox.offering_id}/classification",
            headers=auth(sandbox, idempotency_key=f"f2-noauth-{uuid4().hex}"),
            json={
                "authority_party_id": str(sandbox.party_id),
                "classification_key": classification,
            },
        )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "operational_authority_required"
    assert e2e_admin_conn.execute(
        "SELECT count(*) FROM request_engine.offering_service_classifications "
        "WHERE organization_id=%s AND offering_id=%s",
        (sandbox.organization_id, sandbox.offering_id),
    ).fetchone() == (0,)


@pytest.mark.asyncio
@pytest.mark.e2e
@pytest.mark.postgres
@pytest.mark.security
@pytest.mark.adversarial
async def test_discovery_foreign_offering_is_as_opaque_as_unknown_and_not_mutated(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    owner = seed_tenant_sandbox(e2e_admin_conn, "f2-map-owner")
    foreign = seed_tenant_sandbox(e2e_admin_conn, "f2-map-foreign")
    grant_manage_discovery(e2e_admin_conn, owner)
    classification = create_classification(e2e_admin_conn)
    body = {"authority_party_id": str(owner.party_id), "classification_key": classification}
    async with operational_client(e2e_session_factory, owner) as client:
        foreign_result = await client.put(
            f"/v1/operations/discovery/offerings/{foreign.offering_id}/classification",
            headers=auth(owner, idempotency_key=f"f2-foreign-{uuid4().hex}"),
            json=body,
        )
        unknown_result = await client.put(
            f"/v1/operations/discovery/offerings/{uuid4()}/classification",
            headers=auth(owner, idempotency_key=f"f2-unknown-{uuid4().hex}"),
            json=body,
        )
    assert foreign_result.status_code == 409 == unknown_result.status_code
    assert foreign_result.json()["error"] == unknown_result.json()["error"]
    assert e2e_admin_conn.execute(
        "SELECT count(*) FROM request_engine.offering_service_classifications "
        "WHERE offering_id=%s",
        (foreign.offering_id,),
    ).fetchone() == (0,)
