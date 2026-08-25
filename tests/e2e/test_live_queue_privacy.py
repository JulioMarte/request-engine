from typing import cast
from uuid import UUID, uuid4

import pytest

from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext

from .operational_support import PgConnection
from .tenant_sandbox import auth, client_with_actors, seed_tenant_sandbox


@pytest.mark.asyncio
@pytest.mark.e2e
@pytest.mark.postgres
@pytest.mark.contract
@pytest.mark.security
@pytest.mark.adversarial
async def test_customer_queue_status_cannot_reveal_other_subject_or_staff_execution_fields(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = seed_tenant_sandbox(e2e_admin_conn, "f3-privacy")
    row = e2e_admin_conn.execute(
        "INSERT INTO request_engine.parties (organization_id,party_kind,display_name) "
        "VALUES (%s,'person',%s) RETURNING id",
        (sandbox.organization_id, f"Private Other {uuid4().hex}"),
    ).fetchone()
    assert row is not None
    other_party = cast(UUID, row[0])
    for party_id in (sandbox.party_id, other_party):
        e2e_admin_conn.execute(
            "INSERT INTO request_engine.queue_entries "
            "(organization_id,service_queue_id,subject_party_id) VALUES (%s,%s,%s)",
            (sandbox.organization_id, sandbox.queue_id, party_id),
        )
    actor = ActorContext(
        organization_id=sandbox.organization_id,
        principal_id=sandbox.principal_id,
        capabilities=frozenset({"queue.status"}),
    )
    before = e2e_admin_conn.execute(
        "SELECT count(*) FROM request_engine.queue_entries WHERE service_queue_id=%s",
        (sandbox.queue_id,),
    ).fetchone()
    async with client_with_actors(e2e_session_factory, {sandbox.token: actor}) as client:
        own = await client.get(
            f"/v1/queues/{sandbox.queue_id}/status",
            params={"subject_party_id": str(sandbox.party_id)},
            headers=auth(sandbox),
        )
        foreign = await client.get(
            f"/v1/queues/{sandbox.queue_id}/status",
            params={"subject_party_id": str(other_party)},
            headers=auth(sandbox),
        )
    assert own.status_code == 200, own.text
    assert foreign.status_code == 403, foreign.text
    payload = own.json()
    assert str(other_party) not in own.text
    forbidden = {
        "subject_display_name",
        "expected_workload_key",
        "actual_workload_key",
        "service_session_id",
        "actual_resource_id",
        "actual_location_id",
        "service_started_at",
        "service_completed_at",
    }
    assert forbidden.isdisjoint(payload)
    assert forbidden.isdisjoint(payload.get("entry", {}))
    assert e2e_admin_conn.execute(
        "SELECT count(*) FROM request_engine.queue_entries WHERE service_queue_id=%s",
        (sandbox.queue_id,),
    ).fetchone() == before
