from typing import cast
from uuid import UUID, uuid4

import pytest

from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext

from .operational_support import PgConnection
from .tenant_sandbox import TenantSandbox, auth, client_with_actors, seed_tenant_sandbox


def _seed_called_entry(conn: PgConnection, sandbox: TenantSandbox) -> UUID:
    row = conn.execute(
        "WITH transition AS (SELECT clock_timestamp() AS at) "
        "INSERT INTO request_engine.queue_entries "
        "(organization_id,service_queue_id,subject_party_id,status,"
        "arrived_at,admitted_at,called_at) "
        "SELECT %s,%s,%s,'called',at-interval '2 minutes',at-interval '2 minutes',"
        "at-interval '1 minute' FROM transition RETURNING id",
        (sandbox.organization_id, sandbox.queue_id, sandbox.party_id),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


@pytest.mark.asyncio
@pytest.mark.e2e
@pytest.mark.postgres
@pytest.mark.invariant
@pytest.mark.contract
@pytest.mark.provenance
async def test_start_pause_resume_complete_keeps_queue_and_session_coherent(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = seed_tenant_sandbox(e2e_admin_conn, "f3-service-lifecycle")
    entry_id = _seed_called_entry(e2e_admin_conn, sandbox)
    actor = ActorContext(
        organization_id=sandbox.organization_id,
        principal_id=sandbox.principal_id,
        capabilities=frozenset(
            {
                "service_session.start",
                "service_session.pause",
                "service_session.resume",
                "service_session.complete",
            }
        ),
    )
    async with client_with_actors(e2e_session_factory, {sandbox.token: actor}) as client:
        started = await client.post(
            f"/v1/queue-entries/{entry_id}/service/start",
            json={
                "resource_id": str(sandbox.resource_id),
                "location_id": str(sandbox.location_id),
                "expected_queue_revision": 1,
            },
            headers=auth(sandbox, idempotency_key=f"start-{uuid4().hex}"),
        )
        assert started.status_code == 201, started.text
        session_id = UUID(started.json()["id"])

        paused = await client.post(
            f"/v1/service-sessions/{session_id}/pause",
            json={"expected_revision": 1, "kind": "break"},
            headers=auth(sandbox, idempotency_key=f"pause-{uuid4().hex}"),
        )
        assert paused.status_code == 200, paused.text
        assert paused.json()["status"] == "paused"
        assert e2e_admin_conn.execute(
            "SELECT status,revision FROM request_engine.queue_entries WHERE id=%s",
            (entry_id,),
        ).fetchone() == ("serving", 2)

        resumed = await client.post(
            f"/v1/service-sessions/{session_id}/resume",
            json={"expected_revision": 2},
            headers=auth(sandbox, idempotency_key=f"resume-{uuid4().hex}"),
        )
        assert resumed.status_code == 200, resumed.text
        assert resumed.json()["status"] == "active"
        interruption = e2e_admin_conn.execute(
            "SELECT kind,started_at,ended_at,started_by_principal_id,ended_by_principal_id "
            "FROM request_engine.service_session_interruptions WHERE service_session_id=%s",
            (session_id,),
        ).fetchone()
        assert interruption is not None
        assert interruption[0] == "break"
        assert interruption[2] >= interruption[1]
        assert interruption[3:] == (sandbox.principal_id, sandbox.principal_id)

        completed = await client.post(
            f"/v1/service-sessions/{session_id}/complete",
            json={"expected_revision": 3},
            headers=auth(sandbox, idempotency_key=f"complete-{uuid4().hex}"),
        )
        assert completed.status_code == 200, completed.text

    session_state = e2e_admin_conn.execute(
        "SELECT status,started_at,completed_at,revision FROM request_engine.service_sessions "
        "WHERE id=%s",
        (session_id,),
    ).fetchone()
    queue_state = e2e_admin_conn.execute(
        "SELECT status,service_started_at,completed_at,revision "
        "FROM request_engine.queue_entries WHERE id=%s",
        (entry_id,),
    ).fetchone()
    assert session_state is not None and queue_state is not None
    assert session_state[0] == "completed" and session_state[3] == 4
    assert queue_state[0] == "completed" and queue_state[3] == 3
    assert queue_state[1:3] == session_state[1:3]
