"""`parties.add_contact_point` application command for an existing Party."""

from dataclasses import dataclass, replace
from typing import Protocol
from uuid import UUID

from request_engine.modules.tenancy.contracts.party_registry import (
    PartyContactPoint,
    RegisteredVia,
)
from request_engine.modules.tenancy.domain.party_identity import normalize_party_contact_value


@dataclass(frozen=True, slots=True)
class AddPartyContactPointCommand:
    organization_id: UUID
    principal_id: UUID
    party_id: UUID
    channel: str
    value: str
    registered_via: RegisteredVia
    idempotency_key: str


class AddPartyContactPointHandler(Protocol):
    async def add_party_contact_point(
        self, command: AddPartyContactPointCommand
    ) -> PartyContactPoint: ...


async def add_party_contact_point(
    handler: AddPartyContactPointHandler,
    command: AddPartyContactPointCommand,
) -> PartyContactPoint:
    """Validate and normalize the command, then delegate to the handler.

    The command `value` is replaced by its normalized form; handlers treat it
    as the already-normalized `normalized_value` and must not normalize again.
    Handlers return the affected contact point as it exists after the command.
    """

    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    normalized = normalize_party_contact_value(command.channel, command.value)
    return await handler.add_party_contact_point(replace(command, value=normalized))
