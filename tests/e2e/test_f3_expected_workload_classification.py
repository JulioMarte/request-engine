from typing import cast
from uuid import UUID, uuid4

import pytest

from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext

from .operational_support import PgConnection
from .tenant_sandbox import TenantSandbox, auth, client_with_actors, seed_tenant_sandbox


def _workload(conn: PgConnection, sandbox: TenantSandbox, key: str) -> UUID:
    row = conn.execute(
        "INSERT INTO request_engine.operational_workload_classifications "
        "(organization_id,workload_key,display_name) VALUES (%s,%s,%s) RETURNING id",
        (sandbox.organization_id, key, key.title()),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _called_entry(conn: PgConnection, sandbox: TenantSandbox) -> UUID:
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
@pytest.mark.invariant
@pytest.mark.contract
@pytest.mark.adversarial
@pytest.mark.provenance
async def test_expected_workload_can_change_only_before_service(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = seed_tenant_sandbox(e2e_admin_conn, "f3-workload-classify")
    first = _workload(e2e_admin_conn, sandbox, f"first-{uuid4().hex}")
    second = _workload(e2e_admin_conn, sandbox, f"second-{uuid4().hex}")
    entry_id = _called_entry(e2e_admin_conn, sandbox)
    actor = ActorContext(
        organization_id=sandbox.organization_id,
        principal_id=sandbox.principal_id,
        capabilities=frozenset({"queue.classify_expected_workload", "queue.mark_no_show"}),
    )
    path = f"/v1/queue-entries/{entry_id}/expected-workload"
    async with client_with_actors(e2e_session_factory, {sandbox.token: actor}) as client:
        replay_key = f"classify-{uuid4().hex}"
        first_body = {"expected_revision": 1, "expected_workload_classification_id": str(first)}
        initial = await client.post(path, json=first_body, headers=auth(sandbox, replay_key))
        replay = await client.post(path, json=first_body, headers=auth(sandbox, replay_key))
        changed = await client.post(
            path,
            json={"expected_revision": 2, "expected_workload_classification_id": str(second)},
            headers=auth(sandbox, f"reclassify-{uuid4().hex}"),
        )
        stale = await client.post(
            path,
            json={"expected_revision": 2, "expected_workload_classification_id": str(first)},
            headers=auth(sandbox, f"stale-{uuid4().hex}"),
        )
        cleared = await client.post(
            path,
            json={"expected_revision": 3, "expected_workload_classification_id": None},
            headers=auth(sandbox, f"clear-{uuid4().hex}"),
        )
        no_show = await client.post(
            f"/v1/queue-entries/{entry_id}/no-show",
            json={"expected_revision": 4},
            headers=auth(sandbox, f"no-show-{uuid4().hex}"),
        )
        too_late = await client.post(
            path,
            json={"expected_revision": 5, "expected_workload_classification_id": str(first)},
            headers=auth(sandbox, f"late-{uuid4().hex}"),
        )

    assert initial.status_code == 200 and replay.json() == initial.json()
    assert initial.json()["revision"] == 2
    assert changed.status_code == 200 and changed.json()["revision"] == 3
    assert changed.json()["expected_workload_classification_id"] == str(second)
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "revision_conflict"
    assert cleared.status_code == 200 and cleared.json()["expected_workload_classification_id"] is None
    assert no_show.status_code == 200 and no_show.json()["status"] == "no_show"
    assert too_late.status_code == 409
    assert too_late.json()["error"]["code"] == "queue_entry_not_classifiable"
    assert e2e_admin_conn.execute(
        "SELECT status,expected_workload_classification_id,revision "
        "FROM request_engine.queue_entries WHERE id=%s",
        (entry_id,),
    ).fetchone() == ("no_show", None, 5)
    assert e2e_admin_conn.execute(
        "SELECT count(*) FROM request_engine.audit_records "
        "WHERE command_name='queue.classify_expected_workload' AND aggregate_id=%s",
        (entry_id,),
    ).fetchone() == (3,)
    assert e2e_admin_conn.execute(
        "SELECT count(*) FROM request_engine.outbox_messages "
        "WHERE event_type='queue.entry_expected_workload_classified.v1' AND aggregate_id=%s",
        (entry_id,),
    ).fetchone() == (3,)
