"""Published tenancy party registry connection surfaces."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class PartySourceKind(StrEnum):
    """Whose authority produced an attribution-bearing change (§9.1)."""

    OPERATOR = "operator"
    SUBJECT = "subject"


@dataclass(frozen=True, slots=True)
class PartyContactPointInput:
    channel: str
    value: str


@dataclass(frozen=True, slots=True)
class PartyDocumentInput:
    kind: str
    value: str
    authority: str | None = None


@dataclass(frozen=True, slots=True)
class PartyContactPoint:
    party_id: UUID
    contact_point_id: UUID
    channel: str
    normalized_value: str
    verified: bool
    source_kind: PartySourceKind | None


@dataclass(frozen=True, slots=True)
class PartyIdentityDocument:
    party_id: UUID
    document_id: UUID
    kind: str
    authority: str | None
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


@dataclass(frozen=True, slots=True)
class PartyRevision:
    """One append-only identity revision of a Party (docs/v3/38 §9.3)."""

    revision: int
    change_kind: str
    display_name: str
    active: bool
    source_kind: PartySourceKind | None
    platform: str | None
    actor_principal_id: UUID | None
    attributed_operator_principal_id: UUID | None
    created_at: datetime
    snapshot: Mapping[str, object]
