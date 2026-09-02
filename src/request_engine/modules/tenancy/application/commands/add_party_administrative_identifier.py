"""`parties.add_administrative_identifier` application command."""

from dataclasses import dataclass, replace
from typing import Protocol
from uuid import UUID

from request_engine.modules.tenancy.contracts.party_administrative_identifiers import (
    PartyAdministrativeIdentifier,
)
from request_engine.modules.tenancy.contracts.party_registry import PartySourceKind
from request_engine.modules.tenancy.domain.party_administrative_identifiers import (
    normalize_administrative_identifier_issuer,
    normalize_administrative_identifier_kind,
    normalize_administrative_identifier_value,
)


@dataclass(frozen=True, slots=True)
class AddPartyAdministrativeIdentifierCommand:
    organization_id: UUID
    principal_id: UUID
    party_id: UUID
    kind: str
    issuer: str
    value: str
    source_kind: PartySourceKind
    idempotency_key: str
    normalized_issuer: str = ""
    normalized_value: str = ""
    platform: str | None = None
    technical_principal_id: UUID | None = None


class AddPartyAdministrativeIdentifierHandler(Protocol):
    async def add_party_administrative_identifier(
        self, command: AddPartyAdministrativeIdentifierCommand
    ) -> PartyAdministrativeIdentifier: ...


async def add_party_administrative_identifier(
    handler: AddPartyAdministrativeIdentifierHandler,
    command: AddPartyAdministrativeIdentifierCommand,
) -> PartyAdministrativeIdentifier:
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    kind = normalize_administrative_identifier_kind(command.kind)
    issuer = command.issuer.strip()
    value = command.value.strip()
    normalized_issuer = normalize_administrative_identifier_issuer(issuer)
    normalized_value = normalize_administrative_identifier_value(value)
    return await handler.add_party_administrative_identifier(
        replace(
            command,
            kind=kind.value,
            issuer=issuer,
            value=value,
            normalized_issuer=normalized_issuer,
            normalized_value=normalized_value,
        )
    )
