from uuid import UUID, uuid4

import pytest

from request_engine.platform.db.session import SessionFactory
from tests.e2e.operational_support import PgConnection
from tests.e2e.tenant_sandbox import actor_for, auth, client_with_actors, seed_tenant_sandbox


_WORKLOAD_CAPABILITIES = frozenset({"workload.list", "workload.create", "workload.update"})


@pytest.mark.asyncio
@pytest.mark.e2e
@pytest.mark.postgres
@pytest.mark.security
@pytest.mark.adversarial
async def test_foreign_workload_id_is_as_unusable_as_unknown_id(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    tenant_a = seed_tenant_sandbox(e2e_admin_conn, "f3-workload-a")
    tenant_b = seed_tenant_sandbox(e2e_admin_conn, "f3-workload-b")
    actors = {}
    for tenant in (tenant_a, tenant_b):
        base_actor = actor_for(tenant)
        actors[tenant.token] = type(base_actor)(
            organization_id=base_actor.organization_id,
            principal_id=base_actor.principal_id,
            capabilities=base_actor.capabilities | _WORKLOAD_CAPABILITIES,
        )
    async with client_with_actors(e2e_session_factory, actors) as client:
        created = await client.post(
            "/v1/live-workloads",
            json={"workload_key": "foreign", "display_name": "Foreign"},
            headers=auth(tenant_b, idempotency_key=f"create-{uuid4().hex}"),
        )
        assert created.status_code == 201, created.text
        foreign_id = UUID(created.json()["id"])
        unknown_id = uuid4()
        responses = []
        for workload_id in (foreign_id, unknown_id):
            response = await client.post(
                f"/v1/live-workloads/{workload_id}/update",
                json={"display_name": "Probe", "expected_revision": 1},
                headers=auth(tenant_a, idempotency_key=f"probe-{uuid4().hex}"),
            )
            responses.append(response)
        assert [response.status_code for response in responses] == [404, 404]
        assert [response.json()["error"]["code"] for response in responses] == [
            "workload_classification_not_found",
            "workload_classification_not_found",
        ]
        listed = await client.get("/v1/live-workloads", headers=auth(tenant_a))
        assert listed.json() == []

    assert e2e_admin_conn.execute(
        "SELECT display_name,revision "
        "FROM request_engine.operational_workload_classifications "
        "WHERE organization_id=%s AND id=%s",
        (tenant_b.organization_id, foreign_id),
    ).fetchone() == ("Foreign", 1)
