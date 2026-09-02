"""HTTP DTOs for the consented S0d identity-exchange surface."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from request_engine.modules.tenancy.api.party_registry_models import RegisteredPartyView
from request_engine.modules.tenancy.contracts.identity_exchange import IdentityAdoptionResult

ProofKind = Literal["operator_document_witness"]


class PublishPortableProfileBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    consented_fields: tuple[str, ...] = Field(min_length=1)
    proof_kind: ProofKind


class PublishPortableProfileView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    published: bool = True


class IdentityMatchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_value: str = Field(min_length=1, max_length=64)
    proof_kind: ProofKind


class IdentityMatchView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    matched: bool
    candidate_ref: UUID | None = None


class IdentityAdoptionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_ref: UUID
    document_value: str = Field(min_length=1, max_length=64)
    consented_fields: tuple[str, ...] = Field(min_length=1)
    proof_kind: ProofKind


class PortableInsuranceIdentifierView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issuer: str
    value: str


class IdentityAdoptionView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    party: RegisteredPartyView
    binding_id: UUID
    portable_insurance_identifiers: tuple[PortableInsuranceIdentifierView, ...]

    @classmethod
    def from_contract(cls, result: IdentityAdoptionResult) -> "IdentityAdoptionView":
        return cls(
            party=RegisteredPartyView.from_contract(result.party),
            binding_id=result.binding_id,
            portable_insurance_identifiers=tuple(
                PortableInsuranceIdentifierView(issuer=item.issuer, value=item.value)
                for item in result.portable_insurance_identifiers
            ),
        )
