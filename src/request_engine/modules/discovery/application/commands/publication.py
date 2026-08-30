from typing import Protocol

from request_engine.modules.discovery.contracts.commands import (
    DiscoveryPublicationState,
    PublishDiscoverySupplyCommand,
    RevokeDiscoveryPublicationCommand,
)

__all__ = [
    "DiscoveryPublicationState",
    "PublishDiscoverySupplyCommand",
    "PublishDiscoverySupplyHandler",
    "RevokeDiscoveryPublicationCommand",
    "RevokeDiscoveryPublicationHandler",
    "publish_discovery_supply",
    "revoke_discovery_publication",
]


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
