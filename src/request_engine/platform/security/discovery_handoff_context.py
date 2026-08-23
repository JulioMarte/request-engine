from contextvars import ContextVar, Token
from uuid import UUID

_current_discovery_handoff_id: ContextVar[UUID | None] = ContextVar(
    "request_engine_discovery_handoff_id",
    default=None,
)


def current_discovery_handoff_id() -> UUID | None:
    return _current_discovery_handoff_id.get()


def set_discovery_handoff_id(handoff_id: UUID) -> Token[UUID | None]:
    return _current_discovery_handoff_id.set(handoff_id)


def reset_discovery_handoff_id(token: Token[UUID | None]) -> None:
    _current_discovery_handoff_id.reset(token)
