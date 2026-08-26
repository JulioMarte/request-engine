from uuid import UUID, uuid4

from httpx import AsyncClient, Response

from .tenant_sandbox import TenantSandbox, auth


def response_signature(response: Response) -> tuple[int, str | None]:
    body = response.json()
    error = body.get("error") if isinstance(body, dict) else None
    code = error.get("code") if isinstance(error, dict) else None
    return response.status_code, code


async def post(
    client: AsyncClient,
    sandbox: TenantSandbox,
    path: str,
    body: dict[str, object],
) -> Response:
    return await client.post(
        path,
        json=body,
        headers=auth(sandbox, idempotency_key=f"f4-opacity-{uuid4().hex}"),
    )


async def seed_foreign_policies(
    client: AsyncClient,
    foreign: TenantSandbox,
) -> tuple[str, str]:
    scope = await post(
        client,
        foreign,
        "/v1/live-capacity/projection-policies",
        {
            "service_queue_id": str(foreign.queue_id),
            "resource_id": str(foreign.resource_id),
            "location_id": str(foreign.location_id),
        },
    )
    estimate = await post(
        client,
        foreign,
        "/v1/live-capacity/workload-estimate-policies",
        {
            "workload_classification_id": str(foreign.expected_workload_id),
            "duration_seconds": 1200,
        },
    )
    assert scope.status_code == estimate.status_code == 201
    return scope.json()["id"], estimate.json()["id"]


async def mutation_probe_pairs(
    client: AsyncClient,
    local: TenantSandbox,
    foreign: TenantSandbox,
    foreign_scope_id: str,
    foreign_estimate_id: str,
    unknown: tuple[UUID, UUID, UUID],
) -> list[tuple[Response, Response]]:
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
        {"workload_classification_id": str(foreign.expected_workload_id), "duration_seconds": 1200},
        {"workload_classification_id": str(unknown_a), "duration_seconds": 1200},
    )
    estimate_update = {"duration_seconds": 1200, "active": True, "expected_revision": 1}
    return [
        (
            await post(client, local, "/v1/live-capacity/projection-policies", scope_create[0]),
            await post(client, local, "/v1/live-capacity/projection-policies", scope_create[1]),
        ),
        (
            await post(
                client,
                local,
                f"/v1/live-capacity/projection-policies/{foreign_scope_id}",
                scope_update,
            ),
            await post(client, local, f"/v1/live-capacity/projection-policies/{unknown_a}", scope_update),
        ),
        (
            await post(client, local, "/v1/live-capacity/workload-estimate-policies", estimate_create[0]),
            await post(client, local, "/v1/live-capacity/workload-estimate-policies", estimate_create[1]),
        ),
        (
            await post(
                client,
                local,
                f"/v1/live-capacity/workload-estimate-policies/{foreign_estimate_id}",
                estimate_update,
            ),
            await post(
                client,
                local,
                f"/v1/live-capacity/workload-estimate-policies/{unknown_b}",
                estimate_update,
            ),
        ),
    ]


async def read_probe_pairs(
    client: AsyncClient,
    local: TenantSandbox,
    foreign: TenantSandbox,
    unknown_queue_id: UUID,
    unknown_workload_id: UUID,
) -> list[tuple[Response, Response]]:
    headers = auth(local)
    foreign_base = f"/v1/live-capacity/queues/{foreign.queue_id}"
    unknown_base = f"/v1/live-capacity/queues/{unknown_queue_id}"
    return [
        (await client.get(foreign_base, headers=headers), await client.get(unknown_base, headers=headers)),
        (
            await client.get(
                f"{foreign_base}/evaluate-intake",
                params={"workload_classification_id": str(foreign.expected_workload_id)},
                headers=headers,
            ),
            await client.get(
                f"{unknown_base}/evaluate-intake",
                params={"workload_classification_id": str(unknown_workload_id)},
                headers=headers,
            ),
        ),
        (
            await client.get(
                f"{foreign_base}/customer",
                params={"subject_party_id": str(local.party_id)},
                headers=headers,
            ),
            await client.get(
                f"{unknown_base}/customer",
                params={"subject_party_id": str(local.party_id)},
                headers=headers,
            ),
        ),
    ]
