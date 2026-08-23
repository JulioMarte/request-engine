import asyncio
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
@pytest.mark.concurrency
@pytest.mark.adversarial
async def test_concurrent_first_mapping_has_one_winner_one_loser_and_one_active_mapping(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    tenant = seed_tenant_sandbox(e2e_admin_conn, "f2-map-race")
    grant_manage_discovery(e2e_admin_conn, tenant)
    classification_a = create_classification(e2e_admin_conn, "cardiology")
    classification_b = create_classification(e2e_admin_conn, "dermatology")

    async with operational_client(e2e_session_factory, tenant) as client:

        async def map_to(classification: str) -> object:
            return await client.put(
                f"/v1/operations/discovery/offerings/{tenant.offering_id}/classification",
                headers=auth(tenant, idempotency_key=f"f2-race-{uuid4().hex}"),
                json={
                    "authority_party_id": str(tenant.party_id),
                    "classification_key": classification,
                },
            )

        first, second = await asyncio.gather(map_to(classification_a), map_to(classification_b))

    assert sorted((first.status_code, second.status_code)) == [200, 409]
    active = e2e_admin_conn.execute(
        """
        SELECT sc.classification_key
          FROM request_engine.offering_service_classifications m
          JOIN request_engine.service_classifications sc ON sc.id=m.service_classification_id
         WHERE m.organization_id=%s AND m.offering_id=%s AND m.status='active'
        """,
        (tenant.organization_id, tenant.offering_id),
    ).fetchall()
    assert len(active) == 1
    assert active[0][0] in {classification_a, classification_b}
    assert e2e_admin_conn.execute(
        "SELECT count(*) FROM request_engine.audit_records WHERE organization_id=%s "
        "AND command_name='discovery.map_offering'",
        (tenant.organization_id,),
    ).fetchone() == (1,)
