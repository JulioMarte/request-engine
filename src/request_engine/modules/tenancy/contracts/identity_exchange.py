"""Published tenancy contracts for consented cross-organization identity adoption."""

from dataclasses import dataclass
from uuid import UUID

from request_engine.modules.tenancy.contracts.party_registry import RegisteredParty


@dataclass(frozen=True, slots=True)
class IdentityMatchResult:
    matched: bool
    candidate_ref: UUID | None


@dataclass(frozen=True, slots=True)
class PortableInsuranceIdentifier:
    issuer: str
    value: str


@dataclass(frozen=True, slots=True)
class IdentityAdoptionResult:
    party: RegisteredParty
    binding_id: UUID
    portable_insurance_identifiers: tuple[PortableInsuranceIdentifier, ...] = ()
