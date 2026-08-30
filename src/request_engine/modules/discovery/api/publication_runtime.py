from dataclasses import dataclass

from request_engine.modules.discovery.adapters.db.publish_commands import (
    PostgresDiscoveryPublishCommands,
)
from request_engine.modules.discovery.adapters.db.revoke_commands import (
    PostgresDiscoveryRevokeCommands,
)
from request_engine.modules.discovery.application.commands.publication import (
    PublishDiscoverySupplyHandler,
    RevokeDiscoveryPublicationHandler,
)
from request_engine.modules.discovery.contracts.commands import (
    DiscoveryPublicationState,
    PublishDiscoverySupplyCommand,
    RevokeDiscoveryPublicationCommand,
)
from request_engine.platform.db.session import SessionFactory


@dataclass(frozen=True, slots=True)
class DiscoveryPublicationRuntime:
    publish_handler: PublishDiscoverySupplyHandler
    revoke_handler: RevokeDiscoveryPublicationHandler

    async def publish(
        self,
        command: PublishDiscoverySupplyCommand,
    ) -> DiscoveryPublicationState:
        return await self.publish_handler.publish(command)

    async def revoke(
        self,
        command: RevokeDiscoveryPublicationCommand,
    ) -> DiscoveryPublicationState:
        return await self.revoke_handler.revoke(command)


def build_discovery_publication_runtime(
    session_factory: SessionFactory,
) -> DiscoveryPublicationRuntime:
    return DiscoveryPublicationRuntime(
        publish_handler=PostgresDiscoveryPublishCommands(session_factory),
        revoke_handler=PostgresDiscoveryRevokeCommands(session_factory),
    )
