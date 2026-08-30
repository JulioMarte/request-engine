from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID


class AuthorityKind(StrEnum):
    SELF = "self"
    GUARDIAN = "guardian"
    AUTHORIZED_CONTACT = "authorized_contact"
    DELEGATED = "delegated"


@dataclass(frozen=True, slots=True)
class PartyAuthorityGrant:
    """Current tenant-owned authority provenance for one exact Party scope."""

    representation_id: UUID
    represented_party_id: UUID
    authority_kind: AuthorityKind
    scope_key: str
    valid_from: datetime
    valid_until: datetime | None


class PartyAuthorityReader(Protocol):
    async def resolve_current(
        self,
        *,
        organization_id: UUID,
        principal_id: UUID,
        represented_party_id: UUID,
        scope_key: str,
    ) -> PartyAuthorityGrant | None: ...


class OperationalAuthorityPartyReader(Protocol):
    """Resolve the single party a principal currently holds operational authority for.

    Returns None when the principal holds no current grant within the requested
    scopes, or when grants point at more than one distinct party; callers must
    refuse rather than guess.
    """

    async def resolve_operational_party(
        self,
        *,
        organization_id: UUID,
        principal_id: UUID,
        scope_keys: frozenset[str],
    ) -> UUID | None: ...
