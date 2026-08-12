from typing import Protocol
from uuid import UUID

from request_engine.modules.requests.contracts.request import Request


class RequestReader(Protocol):
    async def get_request(
        self,
        organization_id: UUID,
        request_id: UUID,
    ) -> Request | None: ...


async def get_request_status(
    reader: RequestReader,
    *,
    organization_id: UUID,
    request_id: UUID,
) -> Request | None:
    return await reader.get_request(organization_id, request_id)
