"""HTTP DTOs for the consented S0d identity-exchange surface."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from request_engine.modules.tenancy.api.party_registry_models import RegisteredPartyView
from request_engine.modules.tenancy.contracts.identity_exchange import IdentityAdoptionResult

ProofKind = Literal["operator_document_witness"]
DocumentKind = Literal["cedula", "passport"]


class PublishPortableProfileBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_kind: DocumentKind
    document_authority: str | None = Field(default=None, min_length=1, max_length=64)
    consented_fields: tuple[str, ...] = Field(min_length=1)
    proof_kind: ProofKind


class PublishPortableProfileView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    published: bool


class IdentityMatchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_kind: DocumentKind
    document_authority: str | None = Field(default=None, min_length=1, max_length=64)
    document_value: str = Field(min_length=1, max_length=64)
    proof_kind: ProofKind


class IdentityMatchView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    matched: bool
    candidate_ref: UUID | None = None
    candidate_expires_at: datetime | None = None


class IdentityAdoptionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_ref: UUID
    document_kind: DocumentKind
    document_authority: str | None = Field(default=None, min_length=1, max_length=64)
    document_value: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=200)
    consented_fields: tuple[str, ...] = Field(min_length=1)
    proof_kind: ProofKind


class PortableContactSuggestionView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    channel: str
    value: str


class PortableInsuranceIdentifierView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    issuer: str
    value: str


class IdentityAdoptionView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    party: RegisteredPartyView
    binding_id: UUID
    portable_contact_suggestions: tuple[PortableContactSuggestionView, ...]
    portable_insurance_identifiers: tuple[PortableInsuranceIdentifierView, ...]

    @classmethod
    def from_contract(cls, result: IdentityAdoptionResult) -> "IdentityAdoptionView":
        return cls(
            party=RegisteredPartyView.from_contract(result.party),
            binding_id=result.binding_id,
            portable_contact_suggestions=tuple(
                PortableContactSuggestionView(channel=item.channel, value=item.value)
                for item in result.portable_contact_suggestions
            ),
            portable_insurance_identifiers=tuple(
                PortableInsuranceIdentifierView(issuer=item.issuer, value=item.value)
                for item in result.portable_insurance_identifiers
            ),
        )
