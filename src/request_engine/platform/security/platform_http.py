from typing import Protocol

from fastapi import Request

from request_engine.platform.security.http import CapabilityRequired
from request_engine.platform.security.platform_context import PlatformActorContext


class PlatformActorResolver(Protocol):
    """Inbound HTTP trust-boundary contract for the global platform control plane."""

    async def resolve_platform_actor(self, request: Request) -> PlatformActorContext: ...


def require_platform_capability(actor: PlatformActorContext, capability: str) -> None:
    if not actor.allows(capability):
        raise CapabilityRequired(capability)
