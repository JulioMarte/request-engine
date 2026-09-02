import asyncio
from collections.abc import Mapping
from uuid import uuid4

from httpx import AsyncClient, Response

from .tenant_sandbox import TenantSandbox, auth


async def concurrent_conflicting_posts(
    client: AsyncClient,
    sandbox: TenantSandbox,
    path: str,
    left: Mapping[str, object],
    right: Mapping[str, object],
) -> tuple[Response, Response]:
    headers = auth(sandbox, idempotency_key=f"f6-race-{uuid4().hex}")
    url = f"/v1/operational-copilot/tools{path}"
    first, second = await asyncio.gather(
        client.post(url, json=left, headers=headers),
        client.post(url, json=right, headers=headers),
    )
    assert sorted((first.status_code, second.status_code)) == [200, 409], (
        first.text,
        second.text,
    )
    return first, second


def successful_response(first: Response, second: Response) -> Response:
    return first if first.status_code == 200 else second
