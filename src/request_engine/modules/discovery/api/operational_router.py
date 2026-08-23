from fastapi import APIRouter

from request_engine.modules.discovery.api.operational_mapping_router import (
    create_mapping_router,
)
from request_engine.modules.discovery.api.operational_public_profile_router import (
    create_public_profile_router,
)
from request_engine.modules.discovery.api.operational_publication_router import (
    create_publication_router,
)
from request_engine.modules.discovery.application.commands.mapping import MapOfferingHandler
from request_engine.modules.discovery.application.commands.public_profile import (
    SetResourcePublicProfileHandler,
)
from request_engine.modules.discovery.application.commands.publication import (
    PublishDiscoverySupplyHandler,
    RevokeDiscoveryPublicationHandler,
)
from request_engine.modules.discovery.application.commands.revoke_mapping import (
    RevokeOfferingMappingHandler,
)
from request_engine.platform.security.http import ActorResolver


def create_operational_router(
    *,
    mapping_handler: MapOfferingHandler,
    revoke_mapping_handler: RevokeOfferingMappingHandler,
    public_profile_handler: SetResourcePublicProfileHandler,
    publish_handler: PublishDiscoverySupplyHandler,
    revoke_handler: RevokeDiscoveryPublicationHandler,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter(prefix="/v1/operations/discovery")
    router.include_router(
        create_mapping_router(
            mapping_handler=mapping_handler,
            revoke_mapping_handler=revoke_mapping_handler,
            actor_resolver=actor_resolver,
        )
    )
    router.include_router(
        create_public_profile_router(
            handler=public_profile_handler,
            actor_resolver=actor_resolver,
        )
    )
    router.include_router(
        create_publication_router(
            publish_handler=publish_handler,
            revoke_handler=revoke_handler,
            actor_resolver=actor_resolver,
        )
    )
    return router
