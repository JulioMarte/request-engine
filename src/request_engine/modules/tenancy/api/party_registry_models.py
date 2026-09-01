"""Transport DTOs for the tenancy party registry HTTP surface.

Pydantic belongs here only; application commands and contracts stay
framework-free. `registered_via` is never accepted from clients: the route
derives it server-side from the authenticated principal's authority mode.
"""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from request_engine.modules.tenancy.contracts.party_registry import (
    PartyContactPoint,
    PartyIdentityDocument,
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


class RegisterPartyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str = Field(min_length=1, max_length=512)
    contact_points: tuple[PartyContactPointInputModel, ...] = ()
    documents: tuple[PartyDocumentInputModel, ...] = ()


class AddPartyContactPointBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    channel: str = Field(min_length=1, max_length=64)
    value: str = Field(min_length=1, max_length=256)


class PartyContactPointView(BaseModel):
    contact_point_id: UUID
    channel: str
    normalized_value: str
    verified: bool
    registered_via: str | None = None

    @classmethod
    def from_contract(cls, contact_point: PartyContactPoint) -> "PartyContactPointView":
        return cls(
            contact_point_id=contact_point.contact_point_id,
            channel=contact_point.channel,
            normalized_value=contact_point.normalized_value,
            verified=contact_point.verified,
            registered_via=(
                contact_point.registered_via.value if contact_point.registered_via else None
            ),
        )


class PartyIdentityDocumentView(BaseModel):
    document_id: UUID
    kind: str
    normalized_value: str

    @classmethod
    def from_contract(cls, document: PartyIdentityDocument) -> "PartyIdentityDocumentView":
        return cls(
            document_id=document.document_id,
            kind=document.kind,
            normalized_value=document.normalized_value,
        )


class RegisteredPartyView(BaseModel):
    party_id: UUID
    display_name: str
    active: bool
    contact_points: tuple[PartyContactPointView, ...]
    documents: tuple[PartyIdentityDocumentView, ...]

    @classmethod
    def from_contract(cls, party: RegisteredParty) -> "RegisteredPartyView":
        return cls(
            party_id=party.party_id,
            display_name=party.display_name,
            active=party.active,
            contact_points=tuple(
                PartyContactPointView.from_contract(item) for item in party.contact_points
            ),
            documents=tuple(
                PartyIdentityDocumentView.from_contract(item) for item in party.documents
            ),
        )
