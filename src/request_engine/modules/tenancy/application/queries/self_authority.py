from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from request_engine.modules.tenancy.contracts.authority import AuthorityKind
from request_engine.platform.security.context import ActorContext


class AuthorityInspectionDenied(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SelfAuthorityQuery:
    after: UUID | None = None
    limit: int = 50


@dataclass(frozen=True, slots=True)
class CurrentRepresentation:
    representation_id: UUID
    represented_party_id: UUID
    scope_key: str
    authority_kind: AuthorityKind
    revision: int
    valid_from: datetime
    valid_until: datetime | None


@dataclass(frozen=True, slots=True)
class SelfAuthoritySnapshot:
    principal_id: UUID
    authority_revision: int
    observed_at: datetime
    representations: tuple[CurrentRepresentation, ...]
    next_after: UUID | None


class SelfAuthorityReader(Protocol):
    async def read_self(
        self, actor: ActorContext, query: SelfAuthorityQuery
    ) -> SelfAuthoritySnapshot: ...
