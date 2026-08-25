from typing import cast
from uuid import UUID, uuid4

import pytest

from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext

from .operational_support import PgConnection
from .tenant_sandbox import (
    TenantSandbox,
    auth,
    client_with_actors,
    seed_tenant_sandbox,
)


def _seed_called_entry(conn: PgConnection, sandbox: TenantSandbox) -> UUID:
    conn.execute(
        "INSERT INTO request_engine.resource_location_assignments "
        "(organization_id,resource_id,location_id,effective_during) "
        "VALUES (%s,%s,%s,tstzrange('2020-01-01T00:00Z',NULL,'[)'))",
        (sandbox.organization_id, sandbox.resource_id, sandbox.location_id),
    )
    row = conn.execute(
        "INSERT INTO request_engine.queue_entries "
        "(organization_id,service_queue_id,subject_party_id,status,called_at) "
        "VALUES (%s,%s,%s,'called',clock_timestamp()-interval '1 minute') RETURNING id",
        (sandbox.organization_id, sandbox.queue_id, sandbox.party_id),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


@pytest.mark.asyncio
@pytest.mark.e2e
@pytest.mark.postgres
@pytest.mark.adversarial
async def test_start_service_idempotent_retry_returns_one_authoritative_session(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = seed_tenant_sandbox(e2e_admin_conn, "f3-start-idem")
    entry_id = _seed_called_entry(e2e_admin_conn, sandbox)
    actor = ActorContext(
        organization_id=sandbox.organization_id,
        principal_id=sandbox.principal_id,
        capabilities=frozenset({"service_session.start"}),
    )
    key = f"f3-start-{uuid4().hex}"
    body = {
        "resource_id": str(sandbox.resource_id),
        "location_id": str(sandbox.location_id),
        "expected_queue_revision": 1,
    }
    async with client_with_actors(e2e_session_factory, {sandbox.token: actor}) as client:
        first = await client.post(
            f"/v1/queue-entries/{entry_id}/service/start",
            json=body,
            headers=auth(sandbox, idempotency_key=key),
        )
        replay = await client.post(
            f"/v1/queue-entries/{entry_id}/service/start",
            json=body,
            headers=auth(sandbox, idempotency_key=key),
        )
    assert first.status_code == replay.status_code == 201
    assert first.json() == replay.json()
    assert e2e_admin_conn.execute(
        "SELECT count(*) FROM request_engine.service_sessions WHERE queue_entry_id=%s",
        (entry_id,),
    ).fetchone() == (1,)
    state = e2e_admin_conn.execute(
        "SELECT status,revision,service_started_at FROM request_engine.queue_entries WHERE id=%s",
        (entry_id,),
    ).fetchone()
    assert state is not None
    assert state[0] == "serving"
    assert state[1] == 2
    assert state[2] is not None
