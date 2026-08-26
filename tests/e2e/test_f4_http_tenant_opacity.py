from uuid import uuid4

import pytest
from httpx import AsyncClient, Response

from request_engine.platform.db.session import SessionFactory

from .f4_capacity_support import f4_actor, seed_today_schedule
from .operational_support import PgConnection
from .tenant_sandbox import TenantSandbox, auth, client_with_actors, seed_tenant_sandbox

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e, pytest.mark.postgres, pytest.mark.adversarial, pytest.mark.security]


def _signature(response: Response) -> tuple[int, str | None]:
    body = response.json()
    error = body.get("error") if isinstance(body, dict) else None
    return response.status_code, error.get("code") if isinstance(error, dict) else None


async def _post(client: AsyncClient, sandbox: TenantSandbox, path: str, body: dict[str, object]) -> Response:
    return await client.post(
        path,
        json=body,
        headers=auth(sandbox, idempotency_key=f"f4-opacity-{uuid4().hex}"),
    )


async def _seed_foreign_policies(client: AsyncClient, foreign: TenantSandbox) -> tuple[str, str]:
    scope = await _post(
        client,
        foreign,
        "/v1/live-capacity/projection-policies",
        {
            "service_queue_id": str(foreign.queue_id),
            "resource_id": str(foreign.resource_id),
            "location_id": str(foreign.location_id),
        },
    )
    estimate = await _post(
        client,
        foreign,
        "/v1/live-capacity/workload-estimate-policies",
        {"workload_classification_id": str(foreign.expected_workload_id), "duration_seconds": 1200},
    )
    assert scope.status_code == estimate.status_code == 201
    return scope.json()["id"], estimate.json()["id"]


async def test_f4_public_http_cannot_distinguish_foreign_from_unknown_ids(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    local = seed_tenant_sandbox(e2e_admin_conn, "f4-opacity-local")
    foreign = seed_tenant_sandbox(e2e_admin_conn, "f4-opacity-foreign")
    seed_today_schedule(e2e_admin_conn, local)
    seed_today_schedule(e2e_admin_conn, foreign)
    actors = {local.token: f4_actor(local), foreign.token: f4_actor(foreign)}
    unknown_a, unknown_b, unknown_c = uuid4(), uuid4(), uuid4()

    async with client_with_actors(e2e_session_factory, actors) as client:
        foreign_scope_id, foreign_estimate_id = await _seed_foreign_policies(client, foreign)
        pairs: list[tuple[Response, Response]] = []
        pairs.append(
            (
                await _post(
                    client,
                    local,
                    "/v1/live-capacity/projection-policies",
                    {
                        "service_queue_id": str(foreign.queue_id),
                        "resource_id": str(foreign.resource_id),
                        "location_id": str(foreign.location_id),
                    },
                ),
                await _post(
                    client,
                    local,
                    "/v1/live-capacity/projection-policies",
                    {
                        "service_queue_id": str(unknown_a),
                        "resource_id": str(unknown_b),
                        "location_id": str(unknown_c),
                    },
                ),
            )
        )
        scope_body = {
            "resource_id": str(local.resource_id),
            "location_id": str(local.location_id),
            "active": True,
            "expected_revision": 1,
        }
        pairs.append(
            (
                await _post(client, local, f"/v1/live-capacity/projection-policies/{foreign_scope_id}", scope_body),
                await _post(client, local, f"/v1/live-capacity/projection-policies/{unknown_a}", scope_body),
            )
        )
        pairs.append(
            (
                await _post(
                    client,
                    local,
                    "/v1/live-capacity/workload-estimate-policies",
                    {"workload_classification_id": str(foreign.expected_workload_id), "duration_seconds": 1200},
                ),
                await _post(
                    client,
                    local,
                    "/v1/live-capacity/workload-estimate-policies",
                    {"workload_classification_id": str(unknown_a), "duration_seconds": 1200},
                ),
            )
        )
        estimate_body = {"duration_seconds": 1200, "active": True, "expected_revision": 1}
        pairs.append(
            (
                await _post(
                    client,
                    local,
                    f"/v1/live-capacity/workload-estimate-policies/{foreign_estimate_id}",
                    estimate_body,
                ),
                await _post(
                    client,
                    local,
                    f"/v1/live-capacity/workload-estimate-policies/{unknown_b}",
                    estimate_body,
                ),
            )
        )
        pairs.append(
            (
                await client.get(f"/v1/live-capacity/queues/{foreign.queue_id}", headers=auth(local)),
                await client.get(f"/v1/live-capacity/queues/{unknown_a}", headers=auth(local)),
            )
        )
        pairs.append(
            (
                await client.get(
                    f"/v1/live-capacity/queues/{foreign.queue_id}/evaluate-intake",
                    params={"workload_classification_id": str(foreign.expected_workload_id)},
                    headers=auth(local),
                ),
                await client.get(
                    f"/v1/live-capacity/queues/{unknown_a}/evaluate-intake",
                    params={"workload_classification_id": str(unknown_b)},
                    headers=auth(local),
                ),
            )
        )
        pairs.append(
            (
                await client.get(
                    f"/v1/live-capacity/queues/{foreign.queue_id}/customer",
                    params={"subject_party_id": str(local.party_id)},
                    headers=auth(local),
                ),
                await client.get(
                    f"/v1/live-capacity/queues/{unknown_a}/customer",
                    params={"subject_party_id": str(local.party_id)},
                    headers=auth(local),
                ),
            )
        )

    assert len(pairs) == 7
    for foreign_response, unknown_response in pairs:
        assert _signature(foreign_response) == _signature(unknown_response)
        assert foreign.organization_key not in foreign_response.text
        assert foreign.display_name not in foreign_response.text
