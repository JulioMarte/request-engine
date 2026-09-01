"""`parties.rename` application command: correct a Party display name."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from request_engine.modules.tenancy.contracts.party_registry import RegisteredParty


@dataclass(frozen=True, slots=True)
class RenamePartyCommand:
    organization_id: UUID
    principal_id: UUID
    party_id: UUID
    display_name: str
    idempotency_key: str


class RenamePartyHandler(Protocol):
    async def rename_party(self, command: RenamePartyCommand) -> RegisteredParty: ...


async def rename_party(
    handler: RenamePartyHandler,
    command: RenamePartyCommand,
) -> RegisteredParty:
    """Validate the command, then delegate to the handler.

    The display name is a mutable operator-corrected label: identity facts,
    contact points and documents are untouched. Handlers return the Party as
    it exists after the rename.
    """

    if not command.display_name.strip():
        raise ValueError("display_name is required")
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    return await handler.rename_party(command)
