from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from contextvars import ContextVar, Token
from uuid import UUID, uuid4

from request_engine.platform.security.context import ActorContext, PrincipalKind

_current_actor: ContextVar[ActorContext | None] = ContextVar(
    "request_engine_current_actor",
    default=None,
)


def bind_actor_context(actor: ActorContext) -> Token[ActorContext | None]:
    """Bind one authenticated actor to the current async execution context."""

    return _current_actor.set(actor)


def reset_actor_context(token: Token[ActorContext | None]) -> None:
    """Restore the previous task-local execution context."""

    _current_actor.reset(token)


def clear_actor_context() -> None:
    """Clear actor state at the end of a top-level request execution."""

    _current_actor.set(None)


def current_actor_context() -> ActorContext | None:
    """Return the actor bound to this async task, if any."""

    return _current_actor.get()


@asynccontextmanager
async def system_execution_identity(
    *,
    organization_id: UUID,
    principal_id: UUID,
    principal_kind: PrincipalKind = PrincipalKind.SYSTEM,
    authentication_method: str = "system_execution",
) -> AsyncGenerator[None]:
    """Execute work under one tenant-scoped system identity.

    Cross-boundary sagas run provider-side work under the provider's own
    system principal: the identity replaces any inherited task-local actor
    for the duration, so every transaction framed inside carries honest
    system provenance instead of the caller's identity.
    """

    token = bind_actor_context(
        ActorContext(
            organization_id=organization_id,
            principal_id=principal_id,
            capabilities=frozenset(),
            principal_kind=principal_kind,
            authentication_method=authentication_method,
            correlation_id=uuid4(),
        )
    )
    try:
        yield
    finally:
        reset_actor_context(token)


@asynccontextmanager
async def anonymous_execution_identity() -> AsyncGenerator[None]:
    """Execute tenant-scoped maintenance without any task-local actor identity."""

    inherited = current_actor_context()
    clear_actor_context()
    try:
        yield
    finally:
        if inherited is not None:
            bind_actor_context(inherited)
