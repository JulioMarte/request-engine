from dataclasses import dataclass

from request_engine.modules.discovery.adapters.db.publish_commands import PostgresDiscoveryPublishCommands
from request_engine.modules.discovery.adapters.db.revoke_commands import PostgresDiscoveryRevokeCommands
from request_engine.modules.discovery.application.commands.publication import (
    PublishDiscoverySupplyHandler,
    RevokeDiscoveryPublicationHandler,
)
from request_engine.platform.db.session import SessionFactory


@dataclass(frozen=True, slots=True)
class DiscoveryPublicationRuntime:
    publish: PublishDiscoverySupplyHandler
    revoke: RevokeDiscoveryPublicationHandler


def build_discovery_publication_runtime(
    session_factory: SessionFactory,
) -> DiscoveryPublicationRuntime:
    return DiscoveryPublicationRuntime(
        publish=PostgresDiscoveryPublishCommands(session_factory),
        revoke=PostgresDiscoveryRevokeCommands(session_factory),
    )
