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
