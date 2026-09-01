"""`parties.deactivate_contact_point` application command for an existing Party."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from request_engine.modules.tenancy.contracts.party_registry import (
    PartyContactPoint,
    PartySourceKind,
)


@dataclass(frozen=True, slots=True)
class DeactivatePartyContactPointCommand:
    organization_id: UUID
    principal_id: UUID
    party_id: UUID
    contact_point_id: UUID
    idempotency_key: str
    source_kind: PartySourceKind | None = None
    platform: str | None = None
    technical_principal_id: UUID | None = None


class DeactivatePartyContactPointHandler(Protocol):
    async def deactivate_party_contact_point(
        self, command: DeactivatePartyContactPointCommand
    ) -> PartyContactPoint: ...


async def deactivate_party_contact_point(
    handler: DeactivatePartyContactPointHandler,
    command: DeactivatePartyContactPointCommand,
) -> PartyContactPoint:
    """Validate the command, then delegate to the handler.

    Deactivation flips `active` to false only: `verified` is untouched, so
    verification monotonicity (I-S0b-4) is preserved. Handlers return the
    affected contact point as it exists after the command.
    """

    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    return await handler.deactivate_party_contact_point(command)
