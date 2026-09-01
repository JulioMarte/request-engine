"""`parties.confirm_contact_point` application command (operator-only upstream)."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from request_engine.modules.tenancy.contracts.party_registry import PartyContactPoint


@dataclass(frozen=True, slots=True)
class ConfirmPartyContactPointCommand:
    organization_id: UUID
    principal_id: UUID
    party_id: UUID
    contact_point_id: UUID
    idempotency_key: str


class ConfirmPartyContactPointHandler(Protocol):
    async def confirm_party_contact_point(
        self, command: ConfirmPartyContactPointCommand
    ) -> PartyContactPoint: ...


async def confirm_party_contact_point(
    handler: ConfirmPartyContactPointHandler,
    command: ConfirmPartyContactPointCommand,
) -> PartyContactPoint:
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    return await handler.confirm_party_contact_point(command)
