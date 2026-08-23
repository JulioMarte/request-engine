from fastapi import FastAPI

from request_engine.modules.booking.contracts.discovery import PublishedSlotReader
from request_engine.modules.discovery.adapters.db.mapping_commands import (
    PostgresDiscoveryMappingCommands,
)
from request_engine.modules.discovery.adapters.db.mapping_revoke_commands import (
    PostgresDiscoveryMappingRevokeCommands,
)
from request_engine.modules.discovery.adapters.db.publish_commands import (
    PostgresDiscoveryPublishCommands,
)
from request_engine.modules.discovery.adapters.db.revoke_commands import (
    PostgresDiscoveryRevokeCommands,
)
from request_engine.modules.discovery.api.errors import discovery_search_error_handler
from request_engine.modules.discovery.api.operational_errors import discovery_operational_error_handler
from request_engine.modules.discovery.api.operational_router import create_operational_router
from request_engine.modules.discovery.api.router import create_router
from request_engine.modules.discovery.application.errors import (
    DiscoveryConfigurationConflict,
    DiscoveryRevisionConflict,
    DiscoverySearchContractError,
)
from request_engine.modules.discovery.application.handoff import DiscoveryHandoffIssuer
from request_engine.modules.discovery.application.queries.search_supply import DiscoveryCandidateReader
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.http import ActorResolver
from request_engine.platform.security.platform_discovery import PlatformDiscoveryActorResolver


def install_http(
    app: FastAPI,
    *,
    candidate_reader: DiscoveryCandidateReader,
    actor_resolver: PlatformDiscoveryActorResolver,
    slot_reader: PublishedSlotReader,
    handoff_issuer: DiscoveryHandoffIssuer,
) -> None:
    app.add_exception_handler(DiscoverySearchContractError, discovery_search_error_handler)
    app.include_router(
        create_router(
            candidate_reader=candidate_reader,
            slot_reader=slot_reader,
            handoff_issuer=handoff_issuer,
            actor_resolver=actor_resolver,
        )
    )


def install_operational_http(
    app: FastAPI,
    *,
    session_factory: SessionFactory,
    actor_resolver: ActorResolver,
) -> None:
    for error_type in (DiscoveryConfigurationConflict, DiscoveryRevisionConflict):
        app.add_exception_handler(error_type, discovery_operational_error_handler)
    app.include_router(
        create_operational_router(
            mapping_handler=PostgresDiscoveryMappingCommands(session_factory),
            revoke_mapping_handler=PostgresDiscoveryMappingRevokeCommands(session_factory),
            publish_handler=PostgresDiscoveryPublishCommands(session_factory),
            revoke_handler=PostgresDiscoveryRevokeCommands(session_factory),
            actor_resolver=actor_resolver,
        )
    )
