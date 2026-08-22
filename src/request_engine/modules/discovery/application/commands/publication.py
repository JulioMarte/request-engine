from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class PublishDiscoverySupplyCommand:
    organization_id: UUID
    principal_id: UUID
    authority_party_id: UUID
    offering_id: UUID
    location_id: UUID
    resource_id: UUID | None
    effective_start: datetime
    effective_end: datetime | None
    provider_visibility: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class RevokeDiscoveryPublicationCommand:
    organization_id: UUID
    principal_id: UUID
    authority_party_id: UUID
    publication_id: UUID
    expected_revision: int
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class DiscoveryPublicationState:
    id: UUID
    offering_id: UUID
    location_id: UUID
    resource_id: UUID | None
    effective_start: datetime
    effective_end: datetime | None
    provider_visibility: str
    status: str
    revision: int


class PublishDiscoverySupplyHandler(Protocol):
    async def publish(
        self, command: PublishDiscoverySupplyCommand
    ) -> DiscoveryPublicationState: ...


class RevokeDiscoveryPublicationHandler(Protocol):
    async def revoke(
        self, command: RevokeDiscoveryPublicationCommand
    ) -> DiscoveryPublicationState: ...


async def publish_discovery_supply(
    handler: PublishDiscoverySupplyHandler,
    command: PublishDiscoverySupplyCommand,
) -> DiscoveryPublicationState:
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    return await handler.publish(command)


async def revoke_discovery_publication(
    handler: RevokeDiscoveryPublicationHandler,
    command: RevokeDiscoveryPublicationCommand,
) -> DiscoveryPublicationState:
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    if command.expected_revision < 1:
        raise ValueError("expected_revision must be positive")
    return await handler.revoke(command)
