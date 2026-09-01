"""`parties.lookup` application query: phone / document / name-prefix lookup."""

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from request_engine.modules.tenancy.contracts.party_registry import RegisteredParty
from request_engine.modules.tenancy.domain.party_identity import (
    PartyDocumentKind,
    name_search_key,
    normalize_identity_document,
    normalize_party_contact_value,
)


class PartyLookupMode(StrEnum):
    PHONE = "phone"
    DOCUMENT = "document"
    NAME = "name"


@dataclass(frozen=True, slots=True)
class PartyLookupQuery:
    organization_id: UUID
    mode: PartyLookupMode
    value: str
    document_kind: str = PartyDocumentKind.CEDULA.value


class PartyLookupReader(Protocol):
    async def lookup(self, query: PartyLookupQuery) -> tuple[RegisteredParty, ...]: ...


async def lookup_parties(
    reader: PartyLookupReader,
    query: PartyLookupQuery,
) -> tuple[RegisteredParty, ...]:
    """Normalize the lookup term, then delegate to the reader.

    The reader receives the already-normalized lookup value: an E.164 phone
    number, a normalized identity document value, or the accent-folded name
    search key used as a display-name prefix term.
    """

    if not query.value.strip():
        raise ValueError("lookup value is required")
    if query.mode is PartyLookupMode.PHONE:
        normalized = normalize_party_contact_value("phone", query.value)
        return await reader.lookup(replace(query, value=normalized))
    if query.mode is PartyLookupMode.DOCUMENT:
        normalized = normalize_identity_document(query.document_kind, query.value)
        return await reader.lookup(replace(query, value=normalized))
    return await reader.lookup(replace(query, value=name_search_key(query.value)))
