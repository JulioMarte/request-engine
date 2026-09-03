"""Tenant-owned administrative identifiers attached to a Party."""

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class PartyAdministrativeIdentifierKind(StrEnum):
    INSURANCE_MEMBER = "insurance_member"


@dataclass(frozen=True, slots=True)
class PartyAdministrativeIdentifier:
    identifier_id: UUID
    party_id: UUID
    kind: PartyAdministrativeIdentifierKind
    issuer: str
    normalized_issuer: str
    value: str
    normalized_value: str
    active: bool
