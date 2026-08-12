from typing import Protocol

from fastapi import Request

from request_engine.platform.security.context import ActorContext


class AuthenticationRequired(Exception):
    """Raised when an HTTP authentication adapter cannot resolve an actor."""


class ActorResolver(Protocol):
    """Inbound HTTP trust-boundary contract used by module transport adapters."""

    async def resolve_actor(self, request: Request) -> ActorContext: ...
