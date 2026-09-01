"""Published tenancy party registry connection surfaces."""

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class RegisteredVia(StrEnum):
    OPERATOR = "operator"
    BOT = "bot"


@dataclass(frozen=True, slots=True)
class PartyContactPointInput:
    channel: str
    value: str


@dataclass(frozen=True, slots=True)
class PartyDocumentInput:
    kind: str
    value: str


@dataclass(frozen=True, slots=True)
class PartyContactPoint:
    party_id: UUID
    contact_point_id: UUID
    channel: str
    normalized_value: str
    verified: bool
    registered_via: RegisteredVia | None


@dataclass(frozen=True, slots=True)
class PartyIdentityDocument:
    party_id: UUID
    document_id: UUID
    kind: str
    normalized_value: str


@dataclass(frozen=True, slots=True)
class RegisteredParty:
    party_id: UUID
    organization_id: UUID
    party_kind: str
    display_name: str
    active: bool
    contact_points: tuple[PartyContactPoint, ...]
    documents: tuple[PartyIdentityDocument, ...]
