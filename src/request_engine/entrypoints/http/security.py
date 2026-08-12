from typing import Protocol

from fastapi import Request

from request_engine.platform.security.context import ActorContext


class AuthenticationRequired(Exception):
    """Raised by an HTTP auth adapter when the request has no valid actor."""


class ActorResolver(Protocol):
    async def resolve_actor(self, request: Request) -> ActorContext: ...
