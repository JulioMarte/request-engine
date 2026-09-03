"""HTTP DTOs for Party administrative identifiers."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from request_engine.modules.tenancy.contracts.party_administrative_identifiers import (
    PartyAdministrativeIdentifier,
)


class AddPartyAdministrativeIdentifierBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str = Field(min_length=1, max_length=64)
    issuer: str = Field(min_length=1, max_length=128)
    value: str = Field(min_length=1, max_length=256)


class PartyAdministrativeIdentifierView(BaseModel):
    identifier_id: UUID
    party_id: UUID
    kind: str
    issuer: str
    normalized_issuer: str
    value: str
    normalized_value: str
    active: bool

    @classmethod
    def from_contract(
        cls, identifier: PartyAdministrativeIdentifier
    ) -> "PartyAdministrativeIdentifierView":
        return cls(
            identifier_id=identifier.identifier_id,
            party_id=identifier.party_id,
            kind=identifier.kind.value,
            issuer=identifier.issuer,
            normalized_issuer=identifier.normalized_issuer,
            value=identifier.value,
            normalized_value=identifier.normalized_value,
            active=identifier.active,
        )
