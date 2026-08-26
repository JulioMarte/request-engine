from collections.abc import Mapping
from uuid import UUID, uuid4

from httpx import AsyncClient, Response

from .tenant_sandbox import TenantSandbox, auth


async def _post(
    client: AsyncClient,
    sandbox: TenantSandbox,
    path: str,
    body: Mapping[str, object],
) -> Response:
    return await client.post(
        path,
        json=body,
        headers=auth(sandbox, idempotency_key=f"f4-opacity-{uuid4().hex}"),
    )


async def policy_probe_pairs(
    client: AsyncClient,
    local: TenantSandbox,
    foreign: TenantSandbox,
    foreign_workload_id: UUID,
    foreign_policy_ids: tuple[str, str],
    unknown: tuple[UUID, UUID, UUID],
) -> list[tuple[Response, Response]]:
    foreign_scope_id, foreign_estimate_id = foreign_policy_ids
    unknown_a, unknown_b, unknown_c = unknown
    scope_create = (
        {
            "service_queue_id": str(foreign.queue_id),
            "resource_id": str(foreign.resource_id),
            "location_id": str(foreign.location_id),
        },
        {
            "service_queue_id": str(unknown_a),
            "resource_id": str(unknown_b),
            "location_id": str(unknown_c),
        },
    )
    scope_update = {
        "resource_id": str(local.resource_id),
        "location_id": str(local.location_id),
        "active": True,
        "expected_revision": 1,
    }
    estimate_create = (
        {
            "workload_classification_id": str(foreign_workload_id),
            "duration_seconds": 1200,
        },
        {"workload_classification_id": str(unknown_a), "duration_seconds": 1200},
    )
    estimate_update = {"duration_seconds": 1200, "active": True, "expected_revision": 1}
    return [
        (
            await _post(client, local, "/v1/live-capacity/projection-policies", scope_create[0]),
            await _post(client, local, "/v1/live-capacity/projection-policies", scope_create[1]),
        ),
        (
            await _post(
                client,
                local,
                f"/v1/live-capacity/projection-policies/{foreign_scope_id}",
                scope_update,
            ),
            await _post(
                client,
                local,
                f"/v1/live-capacity/projection-policies/{unknown_a}",
                scope_update,
            ),
        ),
        (
            await _post(
                client,
                local,
                "/v1/live-capacity/workload-estimate-policies",
                estimate_create[0],
            ),
            await _post(
                client,
                local,
                "/v1/live-capacity/workload-estimate-policies",
                estimate_create[1],
            ),
        ),
        (
            await _post(
                client,
                local,
                f"/v1/live-capacity/workload-estimate-policies/{foreign_estimate_id}",
                estimate_update,
            ),
            await _post(
                client,
                local,
                f"/v1/live-capacity/workload-estimate-policies/{unknown_b}",
                estimate_update,
            ),
        ),
    ]
