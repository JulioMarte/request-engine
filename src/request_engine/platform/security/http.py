from dataclasses import replace
from typing import Protocol
from uuid import UUID, uuid4

from fastapi import Request

from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.execution_context import bind_actor_context

REQUEST_CORRELATION_STATE_KEY = "request_engine_correlation_id"


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


class RequestExecutionActorResolver:
    """Bind deployment-authenticated identity to one server-generated request correlation."""

    def __init__(self, delegate: ActorResolver) -> None:
        self._delegate = delegate

    async def resolve_actor(self, request: Request) -> ActorContext:
        actor = await self._delegate.resolve_actor(request)
        correlation_id = request_correlation_id(request)
        bound_actor = replace(actor, correlation_id=correlation_id)
        bind_actor_context(bound_actor)
        return bound_actor


def request_correlation_id(request: Request) -> UUID:
    value = getattr(request.state, REQUEST_CORRELATION_STATE_KEY, None)
    if isinstance(value, UUID):
        return value
    correlation_id = uuid4()
    setattr(request.state, REQUEST_CORRELATION_STATE_KEY, correlation_id)
    return correlation_id


def require_capability(actor: ActorContext, capability: str) -> None:
    """Enforce one canonical capability requirement at an HTTP entrypoint."""

    if not actor.allows(capability):
        raise CapabilityRequired(capability)
