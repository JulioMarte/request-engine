"""Replace the ResourceCapabilities a Resource satisfies.

Changing the set affects only future eligibility (slot search, new Holds and
re-validated claims). Confirmed Reservations keep their CapacityClaims and are
reported as ``retained_commitment_count``; a live Hold depending on a removed
capability makes the command refuse instead of breaking the Hold confirmation.
"""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

MAX_RESOURCE_CAPABILITIES = 50


@dataclass(frozen=True, slots=True)
class ReplaceResourceCapabilitiesCommand:
    organization_id: UUID
    principal_id: UUID
    authority_party_id: UUID
    resource_id: UUID
    capability_ids: tuple[UUID, ...]
    expected_resource_availability_revision: int
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class ResourceCapabilitiesState:
    resource_id: UUID
    capability_ids: tuple[UUID, ...]
    added_capability_ids: tuple[UUID, ...]
    removed_capability_ids: tuple[UUID, ...]
    retained_commitment_count: int
    availability_revision: int


class ReplaceResourceCapabilitiesHandler(Protocol):
    async def replace_resource_capabilities(
        self, command: ReplaceResourceCapabilitiesCommand
    ) -> ResourceCapabilitiesState: ...


def validate_capability_ids(capability_ids: tuple[UUID, ...]) -> None:
    if len(capability_ids) > MAX_RESOURCE_CAPABILITIES:
        raise ValueError(f"at most {MAX_RESOURCE_CAPABILITIES} capability_ids are allowed")
    if len(set(capability_ids)) != len(capability_ids):
        raise ValueError("capability_ids must not repeat")


async def replace_resource_capabilities(
    handler: ReplaceResourceCapabilitiesHandler,
    command: ReplaceResourceCapabilitiesCommand,
) -> ResourceCapabilitiesState:
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    if command.expected_resource_availability_revision <= 0:
        raise ValueError("expected_resource_availability_revision must be positive")
    validate_capability_ids(command.capability_ids)
    return await handler.replace_resource_capabilities(command)
