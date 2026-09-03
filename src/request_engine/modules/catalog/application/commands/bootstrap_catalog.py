from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class CreateResourceCapabilityCommand:
    organization_id: UUID
    principal_id: UUID
    authority_party_id: UUID
    capability_key: str
    display_name: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class ResourceCapabilityState:
    capability_id: UUID
    capability_key: str
    display_name: str


@dataclass(frozen=True, slots=True)
class OfferingRequirementInput:
    capability_id: UUID
    quantity: int = 1


@dataclass(frozen=True, slots=True)
class CreateOfferingCommand:
    organization_id: UUID
    principal_id: UUID
    authority_party_id: UUID
    offering_key: str
    display_name: str
    description: str | None
    duration_minutes: int
    bookable: bool
    requestable: bool
    slot_step_minutes: int
    requirements: tuple[OfferingRequirementInput, ...]
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class OfferingBootstrapState:
    offering_id: UUID
    offering_version_id: UUID
    offering_key: str
    version: int
    requirement_ids: tuple[UUID, ...]


class CatalogBootstrapHandler(Protocol):
    async def create_resource_capability(
        self, command: CreateResourceCapabilityCommand
    ) -> ResourceCapabilityState: ...

    async def create_offering(self, command: CreateOfferingCommand) -> OfferingBootstrapState: ...


async def create_resource_capability(
    handler: CatalogBootstrapHandler,
    command: CreateResourceCapabilityCommand,
) -> ResourceCapabilityState:
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    if not command.capability_key.strip() or not command.display_name.strip():
        raise ValueError("capability_key and display_name are required")
    return await handler.create_resource_capability(command)


async def create_offering(
    handler: CatalogBootstrapHandler,
    command: CreateOfferingCommand,
) -> OfferingBootstrapState:
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    if not command.offering_key.strip() or not command.display_name.strip():
        raise ValueError("offering_key and display_name are required")
    if command.duration_minutes <= 0 or command.slot_step_minutes <= 0:
        raise ValueError("duration_minutes and slot_step_minutes must be positive")
    if len({item.capability_id for item in command.requirements}) != len(command.requirements):
        raise ValueError("requirements must not repeat capability_id")
    if any(item.quantity <= 0 for item in command.requirements):
        raise ValueError("requirement quantity must be positive")
    return await handler.create_offering(command)
