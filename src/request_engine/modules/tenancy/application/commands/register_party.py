"""`parties.register` application command: create a person Party with contacts/documents."""

from dataclasses import dataclass, replace
from typing import Protocol
from uuid import UUID

from request_engine.modules.tenancy.contracts.party_registry import (
    PartyContactPointInput,
    PartyDocumentInput,
    PartySourceKind,
    RegisteredParty,
)
from request_engine.modules.tenancy.domain.party_identity import (
    normalize_identity_document,
    normalize_identity_document_authority,
    normalize_party_contact_value,
)


@dataclass(frozen=True, slots=True)
class RegisterPartyCommand:
    organization_id: UUID
    principal_id: UUID
    display_name: str
    source_kind: PartySourceKind
    idempotency_key: str
    contact_points: tuple[PartyContactPointInput, ...] = ()
    documents: tuple[PartyDocumentInput, ...] = ()
    platform: str | None = None
    technical_principal_id: UUID | None = None


class RegisterPartyHandler(Protocol):
    async def register_party(self, command: RegisterPartyCommand) -> RegisteredParty: ...


async def register_party(
    handler: RegisterPartyHandler,
    command: RegisterPartyCommand,
) -> RegisteredParty:
    """Validate and normalize the command, then delegate to the handler."""

    if not command.display_name.strip():
        raise ValueError("display_name is required")
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    contact_points: list[PartyContactPointInput] = []
    seen_contacts: set[tuple[str, str]] = set()
    for contact in command.contact_points:
        try:
            normalized = normalize_party_contact_value(contact.channel, contact.value)
        except ValueError as error:
            raise ValueError(f"contact point {contact.value!r}: {error}") from None
        key = (contact.channel, normalized)
        if key in seen_contacts:
            raise ValueError(
                f"duplicate contact point: {contact.channel} {contact.value!r}"
                f" (normalized {normalized})"
            )
        seen_contacts.add(key)
        contact_points.append(PartyContactPointInput(contact.channel, normalized))
    documents: list[PartyDocumentInput] = []
    seen_documents: set[tuple[str, str]] = set()
    for document in command.documents:
        try:
            authority = normalize_identity_document_authority(document.kind, document.authority)
            normalized = normalize_identity_document(document.kind, document.value)
        except ValueError as error:
            raise ValueError(f"document {document.value!r}: {error}") from None
        key = (document.kind, authority)
        if key in seen_documents:
            raise ValueError(
                f"duplicate document authority: {document.kind} {authority}"
                f" (value {document.value!r})"
            )
        seen_documents.add(key)
        documents.append(PartyDocumentInput(document.kind, normalized, authority))
    return await handler.register_party(
        replace(command, contact_points=tuple(contact_points), documents=tuple(documents))
    )
