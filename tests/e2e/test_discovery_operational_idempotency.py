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
@pytest.mark.adversarial
async def test_discovery_mapping_replay_is_single_effect_and_conflict_is_non_mutating(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = seed_tenant_sandbox(e2e_admin_conn, "f2-map-replay")
    grant_manage_discovery(e2e_admin_conn, sandbox)
    first_key = create_classification(e2e_admin_conn)
    other_key = create_classification(e2e_admin_conn, "dermatology")
    idem = f"f2-map-{uuid4().hex}"
    body = {
        "authority_party_id": str(sandbox.party_id),
        "classification_key": first_key,
    }

    async with operational_client(e2e_session_factory, sandbox) as client:
        first = await client.put(
            f"/v1/operations/discovery/offerings/{sandbox.offering_id}/classification",
            headers=auth(sandbox, idempotency_key=idem),
            json=body,
        )
        replay = await client.put(
            f"/v1/operations/discovery/offerings/{sandbox.offering_id}/classification",
            headers=auth(sandbox, idempotency_key=idem),
            json=body,
        )
        conflict = await client.put(
            f"/v1/operations/discovery/offerings/{sandbox.offering_id}/classification",
            headers=auth(sandbox, idempotency_key=idem),
            json={**body, "classification_key": other_key},
        )

    assert first.status_code == 200, first.text
    assert replay.status_code == 200 and replay.json() == first.json()
    assert conflict.status_code == 409, conflict.text
    rows = e2e_admin_conn.execute(
        """
        SELECT sc.classification_key
          FROM request_engine.offering_service_classifications m
          JOIN request_engine.service_classifications sc ON sc.id=m.service_classification_id
         WHERE m.organization_id=%s AND m.offering_id=%s AND m.status='active'
        """,
        (sandbox.organization_id, sandbox.offering_id),
    ).fetchall()
    assert rows == [(first_key,)]
    audit = e2e_admin_conn.execute(
        "SELECT count(*) FROM request_engine.audit_records WHERE organization_id=%s "
        "AND command_name='discovery.map_offering'",
        (sandbox.organization_id,),
    ).fetchone()
    assert audit == (1,)
