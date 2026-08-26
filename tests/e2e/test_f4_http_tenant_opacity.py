from typing import cast
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from request_engine.platform.db.session import SessionFactory

from .f4_capacity_support import f4_actor, seed_today_schedule
from .f4_policy_opacity_support import policy_probe_pairs
from .f4_read_opacity_support import read_probe_pairs, response_signature
from .operational_support import PgConnection
from .tenant_sandbox import TenantSandbox, auth, client_with_actors, seed_tenant_sandbox

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.e2e,
    pytest.mark.postgres,
    pytest.mark.adversarial,
    pytest.mark.security,
]


async def _seed_foreign_policies(
    client: AsyncClient,
    foreign: TenantSandbox,
) -> tuple[UUID, tuple[str, str]]:
    workload = await client.post(
        "/v1/live-workloads",
        json={"workload_key": "opacity-foreign", "display_name": "Opacity Foreign"},
        headers=auth(foreign, idempotency_key=f"f4-opacity-workload-{uuid4().hex}"),
    )
    assert workload.status_code == 201, workload.text
    workload_body = cast(dict[str, object], workload.json())
    workload_id = UUID(cast(str, workload_body["id"]))

    scope = await client.post(
        "/v1/live-capacity/projection-policies",
        json={
            "service_queue_id": str(foreign.queue_id),
            "resource_id": str(foreign.resource_id),
            "location_id": str(foreign.location_id),
        },
        headers=auth(foreign, idempotency_key=f"f4-opacity-scope-{uuid4().hex}"),
    )
    estimate = await client.post(
        "/v1/live-capacity/workload-estimate-policies",
        json={"workload_classification_id": str(workload_id), "duration_seconds": 1200},
        headers=auth(foreign, idempotency_key=f"f4-opacity-estimate-{uuid4().hex}"),
    )
    assert scope.status_code == estimate.status_code == 201
    scope_body = cast(dict[str, object], scope.json())
    estimate_body = cast(dict[str, object], estimate.json())
    return workload_id, (cast(str, scope_body["id"]), cast(str, estimate_body["id"]))


async def test_f4_public_http_cannot_distinguish_foreign_from_unknown_ids(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    local = seed_tenant_sandbox(e2e_admin_conn, "f4-opacity-local")
    foreign = seed_tenant_sandbox(e2e_admin_conn, "f4-opacity-foreign")
    seed_today_schedule(e2e_admin_conn, local)
    seed_today_schedule(e2e_admin_conn, foreign)
    actors = {local.token: f4_actor(local), foreign.token: f4_actor(foreign)}
    unknown = (uuid4(), uuid4(), uuid4())

    async with client_with_actors(e2e_session_factory, actors) as client:
        foreign_workload_id, foreign_policy_ids = await _seed_foreign_policies(client, foreign)
        pairs = await policy_probe_pairs(
            client,
            local,
            foreign,
            foreign_workload_id,
            foreign_policy_ids,
            unknown,
        )
        pairs.extend(
            await read_probe_pairs(
                client,
                local,
                foreign,
                foreign_workload_id,
                unknown[0],
                unknown[1],
            )
        )

    assert len(pairs) == 7
    for foreign_response, unknown_response in pairs:
        assert response_signature(foreign_response) == response_signature(unknown_response)
        assert foreign.organization_key not in foreign_response.text
        assert foreign.display_name not in foreign_response.text
