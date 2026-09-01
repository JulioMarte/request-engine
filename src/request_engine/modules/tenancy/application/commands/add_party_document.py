"""`parties.add_document` application command for an existing Party."""

from dataclasses import dataclass, replace
from typing import Protocol
from uuid import UUID

from request_engine.modules.tenancy.contracts.party_registry import (
    PartyIdentityDocument,
    PartySourceKind,
)
from request_engine.modules.tenancy.domain.party_identity import normalize_identity_document


@dataclass(frozen=True, slots=True)
class AddPartyDocumentCommand:
    organization_id: UUID
    principal_id: UUID
    party_id: UUID
    kind: str
    value: str
    source_kind: PartySourceKind
    idempotency_key: str
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
    """Validate and normalize the command, then delegate to the handler.

    The command `value` is replaced by its normalized form; handlers treat it
    as the already-normalized `normalized_value` and must not normalize again.
    Normalization matches `parties.register`, so the same unique active-value
    backstop applies. Handlers return the added document fact.
    """

    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    try:
        normalized = normalize_identity_document(command.kind, command.value)
    except ValueError as error:
        raise ValueError(f"document {command.value!r}: {error}") from None
    return await handler.add_party_document(replace(command, value=normalized))
