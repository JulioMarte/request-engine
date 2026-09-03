from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

CapacityModel = Literal["exclusive", "units"]


@dataclass(frozen=True, slots=True)
class CreateResourceCommand:
    organization_id: UUID
    principal_id: UUID
    authority_party_id: UUID
    location_id: UUID
    resource_key: str
    display_name: str
    capacity_model: CapacityModel
    capacity_units: int
    capability_ids: tuple[UUID, ...]
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class ResourceBootstrapState:
    resource_id: UUID
    resource_key: str
    display_name: str
    capacity_model: CapacityModel
    capacity_units: int
    availability_revision: int
    capability_ids: tuple[UUID, ...]


class CreateResourceHandler(Protocol):
    async def create_resource(self, command: CreateResourceCommand) -> ResourceBootstrapState: ...


async def create_resource(
    handler: CreateResourceHandler,
    command: CreateResourceCommand,
) -> ResourceBootstrapState:
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    if not command.resource_key.strip() or not command.display_name.strip():
        raise ValueError("resource_key and display_name are required")
    if command.capacity_units <= 0:
        raise ValueError("capacity_units must be positive")
    if command.capacity_model == "exclusive" and command.capacity_units != 1:
        raise ValueError("exclusive Resources must have capacity_units=1")
    if len(set(command.capability_ids)) != len(command.capability_ids):
        raise ValueError("capability_ids must not contain duplicates")
    return await handler.create_resource(command)
