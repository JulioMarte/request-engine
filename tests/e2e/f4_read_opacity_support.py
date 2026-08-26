from uuid import UUID

from httpx import AsyncClient, Response

from .tenant_sandbox import TenantSandbox, auth


def response_signature(response: Response) -> tuple[int, str | None]:
    body = response.json()
    error = body.get("error") if isinstance(body, dict) else None
    code = error.get("code") if isinstance(error, dict) else None
    return response.status_code, code


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
        (
            await client.get(foreign_base, headers=headers),
            await client.get(unknown_base, headers=headers),
        ),
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
