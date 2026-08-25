from typing import cast
from uuid import UUID, uuid4

import pytest

from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext

from .operational_support import PgConnection
from .tenant_sandbox import TenantSandbox, auth, client_with_actors, seed_tenant_sandbox


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


def _effect_counts(conn: PgConnection, sandbox: TenantSandbox) -> tuple[int, int]:
    audit = conn.execute(
        "SELECT count(*) FROM request_engine.audit_records "
        "WHERE organization_id=%s AND command_name='service_session.start'",
        (sandbox.organization_id,),
    ).fetchone()
    outbox = conn.execute(
        "SELECT count(*) FROM request_engine.outbox_messages "
        "WHERE organization_id=%s AND event_type='service_session.started.v1'",
        (sandbox.organization_id,),
    ).fetchone()
    assert audit is not None and outbox is not None
    return int(audit[0]), int(outbox[0])


@pytest.mark.asyncio
@pytest.mark.e2e
@pytest.mark.postgres
@pytest.mark.invariant
@pytest.mark.adversarial
@pytest.mark.provenance
async def test_stale_start_service_rejection_leaves_no_authoritative_effects(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = seed_tenant_sandbox(e2e_admin_conn, "f3-start-stale")
    entry_id = _seed_called_entry(e2e_admin_conn, sandbox)
    actor = ActorContext(
        organization_id=sandbox.organization_id,
        principal_id=sandbox.principal_id,
        capabilities=frozenset({"service_session.start"}),
    )
    before_effects = _effect_counts(e2e_admin_conn, sandbox)
    async with client_with_actors(e2e_session_factory, {sandbox.token: actor}) as client:
        response = await client.post(
            f"/v1/queue-entries/{entry_id}/service/start",
            json={
                "resource_id": str(sandbox.resource_id),
                "location_id": str(sandbox.location_id),
                "expected_queue_revision": 99,
            },
            headers=auth(sandbox, idempotency_key=f"stale-start-{uuid4().hex}"),
        )

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "revision_conflict"
    assert e2e_admin_conn.execute(
        "SELECT count(*) FROM request_engine.service_sessions WHERE queue_entry_id=%s",
        (entry_id,),
    ).fetchone() == (0,)
    assert e2e_admin_conn.execute(
        "SELECT status,revision,service_started_at FROM request_engine.queue_entries WHERE id=%s",
        (entry_id,),
    ).fetchone() == ("called", 1, None)
    assert _effect_counts(e2e_admin_conn, sandbox) == before_effects
