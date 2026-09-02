"""Application commands for consented cross-organization Party identity adoption."""

from dataclasses import dataclass, replace
from typing import Protocol
from uuid import UUID

from request_engine.modules.tenancy.contracts.identity_exchange import (
    IdentityAdoptionResult,
    IdentityMatchResult,
)
from request_engine.modules.tenancy.contracts.party_registry import PartySourceKind
from request_engine.modules.tenancy.domain.identity_exchange import (
    normalize_portable_fields,
    normalize_witnessed_document,
    require_adoptable_fields,
)
from request_engine.modules.tenancy.domain.party_identity import (
    normalize_identity_document_authority,
)

_PROOF = "operator_document_witness"


@dataclass(frozen=True, slots=True)
class PublishPortableProfileCommand:
    organization_id: UUID
    principal_id: UUID
    party_id: UUID
    document_kind: str
    document_authority: str | None
    consented_fields: tuple[str, ...]
    proof_kind: str
    idempotency_key: str
    source_kind: PartySourceKind
    platform: str | None = None
    technical_principal_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class MatchPortableIdentityCommand:
    organization_id: UUID
    principal_id: UUID
    document_kind: str
    document_authority: str | None
    document_value: str
    proof_kind: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class AdoptPortableIdentityCommand:
    organization_id: UUID
    principal_id: UUID
    candidate_ref: UUID
    document_kind: str
    document_authority: str | None
    document_value: str
    display_name: str
    consented_fields: tuple[str, ...]
    proof_kind: str
    idempotency_key: str
    source_kind: PartySourceKind
    platform: str | None = None
    technical_principal_id: UUID | None = None


class PublishPortableProfileHandler(Protocol):
    async def publish_portable_profile(self, command: PublishPortableProfileCommand) -> None: ...


class MatchPortableIdentityHandler(Protocol):
    async def match_portable_identity(
        self, command: MatchPortableIdentityCommand
    ) -> IdentityMatchResult: ...


class AdoptPortableIdentityHandler(Protocol):
    async def adopt_portable_identity(
        self, command: AdoptPortableIdentityCommand
    ) -> IdentityAdoptionResult: ...


def _validate_proof(proof_kind: str, idempotency_key: str) -> None:
    if proof_kind != _PROOF:
        raise ValueError(f"unsupported identity proof: {proof_kind}")
    if not idempotency_key:
        raise ValueError("idempotency_key is required")


async def publish_portable_profile(
    handler: PublishPortableProfileHandler,
    command: PublishPortableProfileCommand,
) -> None:
    _validate_proof(command.proof_kind, command.idempotency_key)
    fields = require_adoptable_fields(command.consented_fields)
    authority = normalize_identity_document_authority(
        command.document_kind, command.document_authority
    )
    await handler.publish_portable_profile(
        replace(command, document_authority=authority, consented_fields=fields)
    )


async def match_portable_identity(
    handler: MatchPortableIdentityHandler,
    command: MatchPortableIdentityCommand,
) -> IdentityMatchResult:
    _validate_proof(command.proof_kind, command.idempotency_key)
    document = normalize_witnessed_document(
        command.document_kind, command.document_authority, command.document_value
    )
    return await handler.match_portable_identity(
        replace(
            command,
            document_kind=document.kind,
            document_authority=document.authority,
            document_value=document.value,
        )
    )


async def adopt_portable_identity(
    handler: AdoptPortableIdentityHandler,
    command: AdoptPortableIdentityCommand,
) -> IdentityAdoptionResult:
    _validate_proof(command.proof_kind, command.idempotency_key)
    display_name = command.display_name.strip()
    if not display_name:
        raise ValueError("display_name is required")
    document = normalize_witnessed_document(
        command.document_kind, command.document_authority, command.document_value
    )
    fields = require_adoptable_fields(command.consented_fields)
    return await handler.adopt_portable_identity(
        replace(
            command,
            document_kind=document.kind,
            document_authority=document.authority,
            document_value=document.value,
            display_name=display_name,
            consented_fields=fields,
        )
    )


def portable_fields(fields: tuple[str, ...]) -> tuple[str, ...]:
    return normalize_portable_fields(fields)
