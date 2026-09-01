"""`parties.deactivate` application command: retire a Party from lookups."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from request_engine.modules.tenancy.contracts.party_registry import RegisteredParty


@dataclass(frozen=True, slots=True)
class DeactivatePartyCommand:
    organization_id: UUID
    principal_id: UUID
    party_id: UUID
    idempotency_key: str


class DeactivatePartyHandler(Protocol):
    async def deactivate_party(self, command: DeactivatePartyCommand) -> RegisteredParty: ...


async def deactivate_party(
    handler: DeactivatePartyHandler,
    command: DeactivatePartyCommand,
) -> RegisteredParty:
    """Validate the command, then delegate to the handler.

    Deactivation is idempotent: re-deactivating an already-inactive Party
    succeeds and returns its state. Every other correction on an inactive
    Party fails closed with a typed not-found. Handlers return the Party as
    it exists after the command.
    """

    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    return await handler.deactivate_party(command)
