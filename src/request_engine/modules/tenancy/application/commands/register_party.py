"""`parties.register` application command: create a person Party with contacts/documents."""

from dataclasses import dataclass, replace
from typing import Protocol
from uuid import UUID

from request_engine.modules.tenancy.contracts.party_registry import (
    PartyContactPointInput,
    PartyDocumentInput,
    RegisteredParty,
    RegisteredVia,
)
from request_engine.modules.tenancy.domain.party_identity import (
    normalize_identity_document,
    normalize_party_contact_value,
)


@dataclass(frozen=True, slots=True)
class RegisterPartyCommand:
    organization_id: UUID
    principal_id: UUID
    display_name: str
    registered_via: RegisteredVia
    idempotency_key: str
    contact_points: tuple[PartyContactPointInput, ...] = ()
    documents: tuple[PartyDocumentInput, ...] = ()


class RegisterPartyHandler(Protocol):
    async def register_party(self, command: RegisterPartyCommand) -> RegisteredParty: ...


async def register_party(
    handler: RegisterPartyHandler,
    command: RegisterPartyCommand,
) -> RegisteredParty:
    """Validate and normalize the command, then delegate to the handler.

    This is the single normalization point: handlers receive already-normalized
    contact values and document values and must not normalize again.
    """

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
    seen_kinds: set[str] = set()
    for document in command.documents:
        try:
            normalized = normalize_identity_document(document.kind, document.value)
        except ValueError as error:
            raise ValueError(f"document {document.value!r}: {error}") from None
        if document.kind in seen_kinds:
            raise ValueError(f"duplicate document kind: {document.kind} (value {document.value!r})")
        seen_kinds.add(document.kind)
        documents.append(PartyDocumentInput(document.kind, normalized))
    return await handler.register_party(
        replace(command, contact_points=tuple(contact_points), documents=tuple(documents))
    )
