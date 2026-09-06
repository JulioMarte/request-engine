from typing import cast
from uuid import UUID, uuid4

import pytest

from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext

from .operational_support import PgConnection
from .tenant_sandbox import TenantSandbox, auth, client_with_actors, seed_tenant_sandbox


def _called_entry(conn: PgConnection, sandbox: TenantSandbox) -> UUID:
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


def _actor(sandbox: TenantSandbox) -> ActorContext:
    return ActorContext(
        organization_id=sandbox.organization_id,
        principal_id=sandbox.principal_id,
        capabilities=frozenset(
            {
                "service_session.start",
                "service_session.pause",
                "service_session.read",
                "resource_activity.start",
                "resource_activity.read",
            }
        ),
    )


@pytest.mark.asyncio
@pytest.mark.e2e
@pytest.mark.postgres
@pytest.mark.invariant
@pytest.mark.contract
@pytest.mark.provenance
async def test_service_read_reconstructs_interruption_and_factual_durations(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = seed_tenant_sandbox(e2e_admin_conn, "f3-service-read")
    entry_id = _called_entry(e2e_admin_conn, sandbox)
    async with client_with_actors(e2e_session_factory, {sandbox.token: _actor(sandbox)}) as client:
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
        session_id = started.json()["id"]
        paused = await client.post(
            f"/v1/service-sessions/{session_id}/pause",
            json={"expected_revision": 1, "kind": "break"},
            headers=auth(sandbox, idempotency_key=f"pause-{uuid4().hex}"),
        )
        assert paused.status_code == 200, paused.text
        observed = await client.get(f"/v1/service-sessions/{session_id}", headers=auth(sandbox))

    assert observed.status_code == 200, observed.text
    body = observed.json()
    assert body["status"] == "paused"
    assert body["wall_clock_seconds"] >= body["interruption_seconds"] >= 0
    assert body["active_service_seconds"] == (
        body["wall_clock_seconds"] - body["interruption_seconds"]
    )
    assert len(body["interruptions"]) == 1
    assert body["interruptions"][0]["kind"] == "break"
    assert body["interruptions"][0]["ended_at"] is None


@pytest.mark.asyncio
@pytest.mark.e2e
@pytest.mark.postgres
@pytest.mark.invariant
@pytest.mark.contract
async def test_resource_activity_read_reconstructs_open_occupation(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = seed_tenant_sandbox(e2e_admin_conn, "f3-resource-read")
    actor = _actor(sandbox)
    async with client_with_actors(e2e_session_factory, {sandbox.token: actor}) as client:
        started = await client.post(
            "/v1/resource-activities",
            json={"resource_id": str(sandbox.resource_id), "kind": "administrative"},
            headers=auth(sandbox, idempotency_key=f"activity-{uuid4().hex}"),
        )
        assert started.status_code == 201, started.text
        observed = await client.get(
            "/v1/resource-activities",
            params={"resource_id": str(sandbox.resource_id)},
            headers=auth(sandbox),
        )

    assert observed.status_code == 200, observed.text
    assert len(observed.json()) == 1
    assert observed.json()[0]["id"] == started.json()["id"]
    assert observed.json()[0]["kind"] == "administrative"
    assert observed.json()[0]["ended_at"] is None
