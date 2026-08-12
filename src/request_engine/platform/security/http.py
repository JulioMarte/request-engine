from typing import Protocol

from fastapi import Request

from request_engine.platform.security.context import ActorContext


class AuthenticationRequired(Exception):
    """Raised when an HTTP authentication adapter cannot resolve an actor."""


class CapabilityRequired(Exception):
    """Raised when an authenticated actor lacks a required technical capability."""

    def __init__(self, capability: str) -> None:
        super().__init__(f"capability {capability!r} is required")
        self.capability = capability


class ActorResolver(Protocol):
    """Inbound HTTP trust-boundary contract used by module transport adapters."""

    async def resolve_actor(self, request: Request) -> ActorContext: ...


def require_capability(actor: ActorContext, capability: str) -> None:
    """Enforce one canonical capability requirement at an HTTP entrypoint."""

    if not actor.allows(capability):
        raise CapabilityRequired(capability)
