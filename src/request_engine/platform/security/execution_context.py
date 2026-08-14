from contextvars import ContextVar, Token

from request_engine.platform.security.context import ActorContext

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
