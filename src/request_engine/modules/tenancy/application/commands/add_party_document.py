"""`parties.add_document` application command for an existing Party."""

from dataclasses import dataclass, replace
from typing import Protocol
from uuid import UUID

from request_engine.modules.tenancy.contracts.party_registry import (
    PartyIdentityDocument,
    PartySourceKind,
)
from request_engine.modules.tenancy.domain.party_identity import (
    normalize_identity_document,
    normalize_identity_document_authority,
)


@dataclass(frozen=True, slots=True)
class AddPartyDocumentCommand:
    organization_id: UUID
    principal_id: UUID
    party_id: UUID
    kind: str
    value: str
    source_kind: PartySourceKind
    idempotency_key: str
    authority: str | None = None
    platform: str | None = None
    technical_principal_id: UUID | None = None


class AddPartyDocumentHandler(Protocol):
    async def add_party_document(
        self, command: AddPartyDocumentCommand
    ) -> PartyIdentityDocument: ...


async def add_party_document(
    handler: AddPartyDocumentHandler,
    command: AddPartyDocumentCommand,
) -> PartyIdentityDocument:
    """Validate and normalize document value and issuer before persistence."""

    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    try:
        authority = normalize_identity_document_authority(command.kind, command.authority)
        normalized = normalize_identity_document(command.kind, command.value)
    except ValueError as error:
        raise ValueError(f"document {command.value!r}: {error}") from None
    return await handler.add_party_document(replace(command, value=normalized, authority=authority))
