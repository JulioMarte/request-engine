from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class CreateServiceQueueCommand:
    organization_id: UUID
    principal_id: UUID
    authority_party_id: UUID
    location_id: UUID
    offering_id: UUID | None
    queue_key: str
    display_name: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class ServiceQueueBootstrapState:
    queue_id: UUID
    queue_key: str
    display_name: str
    location_id: UUID
    offering_id: UUID | None


class CreateServiceQueueHandler(Protocol):
    async def create_service_queue(
        self, command: CreateServiceQueueCommand
    ) -> ServiceQueueBootstrapState: ...


async def create_service_queue(
    handler: CreateServiceQueueHandler,
    command: CreateServiceQueueCommand,
) -> ServiceQueueBootstrapState:
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    if not command.queue_key.strip() or not command.display_name.strip():
        raise ValueError("queue_key and display_name are required")
    return await handler.create_service_queue(command)
