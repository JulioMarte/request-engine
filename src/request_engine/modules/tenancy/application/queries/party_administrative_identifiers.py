"""Read queries for tenant-owned Party administrative identifiers."""

from dataclasses import dataclass, replace
from typing import Protocol
from uuid import UUID

from request_engine.modules.tenancy.contracts.party_administrative_identifiers import (
    PartyAdministrativeIdentifier,
)
from request_engine.modules.tenancy.contracts.party_registry import RegisteredParty
from request_engine.modules.tenancy.domain.party_administrative_identifiers import (
    normalize_administrative_identifier_issuer,
    normalize_administrative_identifier_kind,
    normalize_administrative_identifier_value,
)


@dataclass(frozen=True, slots=True)
class PartyAdministrativeIdentifierListQuery:
    organization_id: UUID
    party_id: UUID


@dataclass(frozen=True, slots=True)
class PartyAdministrativeIdentifierLookupQuery:
    organization_id: UUID
    kind: str
    issuer: str
    value: str


class PartyAdministrativeIdentifierReader(Protocol):
    async def list_for_party(
        self, query: PartyAdministrativeIdentifierListQuery
    ) -> tuple[PartyAdministrativeIdentifier, ...]: ...

    async def lookup_party(
        self, query: PartyAdministrativeIdentifierLookupQuery
    ) -> tuple[RegisteredParty, ...]: ...


async def lookup_party_by_administrative_identifier(
    reader: PartyAdministrativeIdentifierReader,
    query: PartyAdministrativeIdentifierLookupQuery,
) -> tuple[RegisteredParty, ...]:
    kind = normalize_administrative_identifier_kind(query.kind)
    normalized_issuer = normalize_administrative_identifier_issuer(query.issuer)
    normalized_value = normalize_administrative_identifier_value(query.value)
    return await reader.lookup_party(
        replace(
            query,
            kind=kind.value,
            issuer=normalized_issuer,
            value=normalized_value,
        )
    )
