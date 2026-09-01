"""`parties.rollback_identity` application command: restore a prior revision."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from request_engine.modules.tenancy.contracts.party_registry import (
    PartySourceKind,
    RegisteredParty,
)


@dataclass(frozen=True, slots=True)
class RollbackPartyIdentityCommand:
    organization_id: UUID
    principal_id: UUID
    party_id: UUID
    target_revision: int
    idempotency_key: str
    source_kind: PartySourceKind | None = None
    platform: str | None = None
    technical_principal_id: UUID | None = None


class RollbackPartyIdentityHandler(Protocol):
    async def rollback_party_identity(
        self, command: RollbackPartyIdentityCommand
    ) -> RegisteredParty: ...


async def rollback_party_identity(
    handler: RollbackPartyIdentityHandler,
    command: RollbackPartyIdentityCommand,
) -> RegisteredParty:
    """Validate the command, then delegate to the handler.

    Rollback applies a prior revision's recorded snapshot as a NEW ledger
    revision: history is never rewritten or deleted. It is allowed on
    inactive Parties (that is its main use). Verification remains monotone
    (I-S0b-4) and is never rolled back.
    """

    if command.target_revision < 1:
        raise ValueError("target_revision must be >= 1")
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    return await handler.rollback_party_identity(command)
