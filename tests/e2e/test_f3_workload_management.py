from uuid import UUID, uuid4

import pytest

from request_engine.platform.db.session import SessionFactory

from .operational_support import PgConnection
from .tenant_sandbox import actor_for, auth, client_with_actors, seed_tenant_sandbox


@pytest.mark.asyncio
@pytest.mark.e2e
@pytest.mark.postgres
@pytest.mark.contract
@pytest.mark.adversarial
async def test_workload_vocabulary_is_revisioned_idempotent_and_deactivatable(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = seed_tenant_sandbox(e2e_admin_conn, "f3-workload-management")
    base_actor = actor_for(sandbox)
    actor = type(base_actor)(
        organization_id=base_actor.organization_id,
        principal_id=base_actor.principal_id,
        capabilities=base_actor.capabilities
        | frozenset(
            {
                "workload.list",
                "workload.create",
                "workload.update",
                "workload.deactivate",
            }
        ),
    )
    create_key = f"create-{uuid4().hex}"
    async with client_with_actors(e2e_session_factory, {sandbox.token: actor}) as client:
        created = await client.post(
            "/v1/live-workloads",
            json={"workload_key": "consultation", "display_name": "Consultation"},
            headers=auth(sandbox, idempotency_key=create_key),
        )
        replay = await client.post(
            "/v1/live-workloads",
            json={"workload_key": "consultation", "display_name": "Consultation"},
            headers=auth(sandbox, idempotency_key=create_key),
        )
        assert created.status_code == replay.status_code == 201
        assert created.json() == replay.json()
        workload_id = UUID(created.json()["id"])

        updated = await client.post(
            f"/v1/live-workloads/{workload_id}/update",
            json={"display_name": "Consult", "expected_revision": 1},
            headers=auth(sandbox, idempotency_key=f"update-{uuid4().hex}"),
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["workload_key"] == "consultation"
        assert updated.json()["display_name"] == "Consult"
        assert updated.json()["revision"] == 2

        stale = await client.post(
            f"/v1/live-workloads/{workload_id}/update",
            json={"display_name": "Stale", "expected_revision": 1},
            headers=auth(sandbox, idempotency_key=f"stale-{uuid4().hex}"),
        )
        assert stale.status_code == 409
        listed = await client.get("/v1/live-workloads", headers=auth(sandbox))
        assert [item["display_name"] for item in listed.json()] == ["Consult"]

        deactivated = await client.post(
            f"/v1/live-workloads/{workload_id}/deactivate",
            json={"expected_revision": 2},
            headers=auth(sandbox, idempotency_key=f"deactivate-{uuid4().hex}"),
        )
        assert deactivated.status_code == 200, deactivated.text
        assert deactivated.json()["active"] is False
        assert deactivated.json()["revision"] == 3
        assert (await client.get("/v1/live-workloads", headers=auth(sandbox))).json() == []

    assert e2e_admin_conn.execute(
        "SELECT workload_key,display_name,active,revision "
        "FROM request_engine.operational_workload_classifications WHERE id=%s",
        (workload_id,),
    ).fetchone() == ("consultation", "Consult", False, 3)
    assert e2e_admin_conn.execute(
        "SELECT count(*) FROM request_engine.audit_records "
        "WHERE organization_id=%s AND aggregate_kind='OperationalWorkloadClassification'",
        (sandbox.organization_id,),
    ).fetchone() == (3,)
    assert e2e_admin_conn.execute(
        "SELECT count(*) FROM request_engine.outbox_messages "
        "WHERE organization_id=%s AND aggregate_kind='OperationalWorkloadClassification'",
        (sandbox.organization_id,),
    ).fetchone() == (3,)
