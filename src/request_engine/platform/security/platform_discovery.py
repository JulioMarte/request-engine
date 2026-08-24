from dataclasses import dataclass, field, replace
from typing import Protocol
from uuid import UUID, uuid4

from fastapi import Request

from request_engine.platform.security.capabilities import grant_satisfies
from request_engine.platform.security.context import PrincipalKind
from request_engine.platform.security.http import CapabilityRequired, request_correlation_id

DISCOVERY_SEARCH_CAPABILITY = "discovery.search_supply"
DISCOVERY_SLOT_READ_CAPABILITY = "discovery.read_published_slots"


@dataclass(frozen=True, slots=True)
class PlatformDiscoveryActor:
    principal_id: UUID
    capabilities: frozenset[str]
    principal_kind: PrincipalKind = PrincipalKind.INTEGRATION
    authentication_method: str = "deployment_adapter"
    correlation_id: UUID = field(default_factory=uuid4)
    credential_id: str | None = None

    def __post_init__(self) -> None:
        if not self.authentication_method.strip():
            raise ValueError("authentication_method is required")
        if self.credential_id is not None and not self.credential_id.strip():
            raise ValueError("credential_id cannot be blank")

    def allows(self, capability: str) -> bool:
        return any(grant_satisfies(granted, capability) for granted in self.capabilities)


class PlatformDiscoveryActorResolver(Protocol):
    async def resolve_actor(self, request: Request) -> PlatformDiscoveryActor: ...


class RequestPlatformDiscoveryActorResolver:
    def __init__(self, delegate: PlatformDiscoveryActorResolver) -> None:
        self._delegate = delegate

    async def resolve_actor(self, request: Request) -> PlatformDiscoveryActor:
        actor = await self._delegate.resolve_actor(request)
        return replace(actor, correlation_id=request_correlation_id(request))


def require_platform_discovery_capability(
    actor: PlatformDiscoveryActor, capability: str = DISCOVERY_SEARCH_CAPABILITY
) -> None:
    if not actor.allows(capability):
        raise CapabilityRequired(capability)
