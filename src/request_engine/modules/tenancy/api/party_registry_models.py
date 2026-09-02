"""Transport DTOs for the tenancy party registry HTTP surface."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from request_engine.modules.tenancy.contracts.party_kind import PartyKind
from request_engine.modules.tenancy.contracts.party_registry import (
    PartyContactPoint,
    PartyIdentityDocument,
    PartyRevision,
    RegisteredParty,
)


class PartyContactPointInputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    channel: str = Field(min_length=1, max_length=64)
    value: str = Field(min_length=1, max_length=256)


class PartyDocumentInputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str = Field(min_length=1, max_length=64)
    value: str = Field(min_length=1, max_length=256)
    authority: str | None = Field(default=None, min_length=1, max_length=64)


class RegisterPartyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    party_kind: PartyKind = PartyKind.PERSON
    display_name: str = Field(min_length=1, max_length=512)
    contact_points: tuple[PartyContactPointInputModel, ...] = ()
    documents: tuple[PartyDocumentInputModel, ...] = ()


class AddPartyContactPointBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    channel: str = Field(min_length=1, max_length=64)
    value: str = Field(min_length=1, max_length=256)


class RenamePartyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str = Field(min_length=1, max_length=512)


class AddPartyDocumentBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str = Field(min_length=1, max_length=64)
    value: str = Field(min_length=1, max_length=256)
    authority: str | None = Field(default=None, min_length=1, max_length=64)


class RollbackPartyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_revision: int = Field(ge=1)


class PartyContactPointView(BaseModel):
    contact_point_id: UUID
    channel: str
    normalized_value: str
    verified: bool
    source_kind: str | None = None

    @classmethod
    def from_contract(cls, contact_point: PartyContactPoint) -> "PartyContactPointView":
        return cls(
            contact_point_id=contact_point.contact_point_id,
            channel=contact_point.channel,
            normalized_value=contact_point.normalized_value,
            verified=contact_point.verified,
            source_kind=(contact_point.source_kind.value if contact_point.source_kind else None),
        )


class PartyIdentityDocumentView(BaseModel):
    document_id: UUID
    kind: str
    authority: str | None
    normalized_value: str

    @classmethod
    def from_contract(cls, document: PartyIdentityDocument) -> "PartyIdentityDocumentView":
        return cls(
            document_id=document.document_id,
            kind=document.kind,
            authority=document.authority,
            normalized_value=document.normalized_value,
        )


class RegisteredPartyView(BaseModel):
    party_id: UUID
    party_kind: PartyKind
    display_name: str
    active: bool
    contact_points: tuple[PartyContactPointView, ...]
    documents: tuple[PartyIdentityDocumentView, ...]

    @classmethod
    def from_contract(cls, party: RegisteredParty) -> "RegisteredPartyView":
        return cls(
            party_id=party.party_id,
            party_kind=PartyKind(party.party_kind),
            display_name=party.display_name,
            active=party.active,
            contact_points=tuple(
                PartyContactPointView.from_contract(item) for item in party.contact_points
            ),
            documents=tuple(
                PartyIdentityDocumentView.from_contract(item) for item in party.documents
            ),
        )


class PartyRevisionView(BaseModel):
    revision: int
    change_kind: str
    display_name: str
    active: bool
    source_kind: str | None = None
    platform: str | None = None
    actor_principal_id: UUID | None = None
    attributed_operator_principal_id: UUID | None = None
    created_at: datetime
    snapshot: dict[str, object]

    @classmethod
    def from_contract(cls, revision: PartyRevision) -> "PartyRevisionView":
        return cls(
            revision=revision.revision,
            change_kind=revision.change_kind,
            display_name=revision.display_name,
            active=revision.active,
            source_kind=(revision.source_kind.value if revision.source_kind else None),
            platform=revision.platform,
            actor_principal_id=revision.actor_principal_id,
            attributed_operator_principal_id=revision.attributed_operator_principal_id,
            created_at=revision.created_at,
            snapshot=dict(revision.snapshot),
        )
