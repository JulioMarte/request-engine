from typing import Protocol
from uuid import UUID

from request_engine.modules.requests.contracts.definitions import (
    ResolvedRequestDefinitionVersion,
)


class RequestDefinitionResolver(Protocol):
    async def resolve_request_definition(
        self,
        *,
        organization_id: UUID,
        request_key: str,
        version: int | None,
    ) -> ResolvedRequestDefinitionVersion: ...


async def resolve_request_definition(
    resolver: RequestDefinitionResolver,
    *,
    organization_id: UUID,
    request_key: str,
    version: int | None,
) -> ResolvedRequestDefinitionVersion:
    if not request_key:
        raise ValueError("request_key is required")
    if version is not None and version <= 0:
        raise ValueError("version must be positive")
    return await resolver.resolve_request_definition(
        organization_id=organization_id,
        request_key=request_key,
        version=version,
    )
