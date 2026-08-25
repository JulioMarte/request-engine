from typing import cast
from uuid import UUID, uuid4

import pytest

from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext

from .operational_support import PgConnection
from .tenant_sandbox import TenantSandbox, auth, client_with_actors, seed_tenant_sandbox


def _entry(conn: PgConnection, sandbox: TenantSandbox) -> UUID:
    row = conn.execute(
        "INSERT INTO request_engine.queue_entries "
        "(organization_id,service_queue_id,subject_party_id) VALUES (%s,%s,%s) RETURNING id",
        (sandbox.organization_id, sandbox.queue_id, sandbox.party_id),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _workload(conn: PgConnection, sandbox: TenantSandbox, key: str) -> UUID:
    row = conn.execute(
        "INSERT INTO request_engine.operational_workload_classifications "
        "(organization_id,workload_key,display_name) VALUES (%s,%s,%s) RETURNING id",
        (sandbox.organization_id, key, key),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _actor(sandbox: TenantSandbox) -> ActorContext:
    return ActorContext(
        organization_id=sandbox.organization_id,
        principal_id=sandbox.principal_id,
        capabilities=frozenset({"queue.classify_expected_workload"}),
    )


@pytest.mark.asyncio
@pytest.mark.e2e
@pytest.mark.postgres
@pytest.mark.adversarial
async def test_classification_conflicting_idempotency_reuse_has_no_second_effect(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = seed_tenant_sandbox(e2e_admin_conn, "f3-classify-idem-conflict")
    entry_id = _entry(e2e_admin_conn, sandbox)
    first = _workload(e2e_admin_conn, sandbox, f"first-{uuid4().hex}")
    second = _workload(e2e_admin_conn, sandbox, f"second-{uuid4().hex}")
    key = f"classify-{uuid4().hex}"
    path = f"/v1/queue-entries/{entry_id}/expected-workload"
    async with client_with_actors(e2e_session_factory, {sandbox.token: _actor(sandbox)}) as client:
        accepted = await client.post(
            path,
            json={"expected_revision": 1, "expected_workload_classification_id": str(first)},
            headers=auth(sandbox, idempotency_key=key),
        )
        conflict = await client.post(
            path,
            json={"expected_revision": 2, "expected_workload_classification_id": str(second)},
            headers=auth(sandbox, idempotency_key=key),
        )
    assert accepted.status_code == 200
    assert conflict.status_code == 409
    assert e2e_admin_conn.execute(
        "SELECT expected_workload_classification_id,revision "
        "FROM request_engine.queue_entries WHERE id=%s",
        (entry_id,),
    ).fetchone() == (first, 2)


@pytest.mark.asyncio
@pytest.mark.e2e
@pytest.mark.postgres
@pytest.mark.adversarial
@pytest.mark.security
async def test_classification_foreign_workload_is_opaque(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    local = seed_tenant_sandbox(e2e_admin_conn, "f3-classify-local")
    foreign = seed_tenant_sandbox(e2e_admin_conn, "f3-classify-foreign")
    entry_id = _entry(e2e_admin_conn, local)
    foreign_workload = _workload(e2e_admin_conn, foreign, f"foreign-{uuid4().hex}")
    path = f"/v1/queue-entries/{entry_id}/expected-workload"
    async with client_with_actors(e2e_session_factory, {local.token: _actor(local)}) as client:
        foreign_response = await client.post(
            path,
            json={
                "expected_revision": 1,
                "expected_workload_classification_id": str(foreign_workload),
            },
            headers=auth(local, idempotency_key=f"foreign-{uuid4().hex}"),
        )
        random_response = await client.post(
            path,
            json={"expected_revision": 1, "expected_workload_classification_id": str(uuid4())},
            headers=auth(local, idempotency_key=f"random-{uuid4().hex}"),
        )
    assert foreign_response.status_code == random_response.status_code == 422
    assert foreign_response.json()["error"] == random_response.json()["error"]
    assert e2e_admin_conn.execute(
        "SELECT expected_workload_classification_id,revision "
        "FROM request_engine.queue_entries WHERE id=%s",
        (entry_id,),
    ).fetchone() == (None, 1)
