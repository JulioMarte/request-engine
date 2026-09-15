from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from request_engine.platform.security.context import ActorContext

IDENTITY_BINDING_READ_CAPABILITY = "identity.binding.read"

_BINDING_STATUSES = frozenset({"pending", "active", "suspended", "revoked"})


@dataclass(frozen=True, slots=True)
class IdentityBindingView:
    """Tenant-scoped binding projection; never carries subject_id or verifiers."""

    binding_id: UUID
    principal_id: UUID
    identity_authority_id: UUID
    status: str
    revision: int
    created_at: datetime

    def __post_init__(self) -> None:
        if self.revision < 1:
            raise ValueError("binding revision must be positive")


class IdentityBindingReadError(RuntimeError):
    """Bounded identity binding read failure."""


class IdentityBindingReadForbidden(IdentityBindingReadError):
    pass


class IdentityBindingNotFound(IdentityBindingReadError):
    pass


class IdentityBindingReadInvalid(IdentityBindingReadError):
    pass


@dataclass(frozen=True, slots=True)
class ListIdentityBindingsQuery:
    principal_id: UUID | None = None
    status: str | None = None
    after: UUID | None = None
    limit: int = 50

    def __post_init__(self) -> None:
        if not 1 <= self.limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        if self.status is not None and self.status not in _BINDING_STATUSES:
            raise ValueError("status filter is not an accepted identity binding status")


@dataclass(frozen=True, slots=True)
class GetIdentityBindingQuery:
    binding_id: UUID


class IdentityBindingReader(Protocol):
    async def list_bindings(
        self,
        actor: ActorContext,
        query: ListIdentityBindingsQuery,
    ) -> tuple[IdentityBindingView, ...]: ...

    async def read_binding(
        self,
        actor: ActorContext,
        query: GetIdentityBindingQuery,
    ) -> IdentityBindingView: ...
