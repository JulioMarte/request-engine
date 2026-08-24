from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from request_engine.modules.discovery.api.operational_models import (
    DiscoveryPublicationBody,
    RevokeDiscoveryConfigurationBody,
)
from request_engine.modules.discovery.application.commands.publication import (
    PublishDiscoverySupplyCommand,
    PublishDiscoverySupplyHandler,
    RevokeDiscoveryPublicationCommand,
    RevokeDiscoveryPublicationHandler,
    publish_discovery_supply,
    revoke_discovery_publication,
)
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver

from .operational_router_types import IdempotencyKey


def create_publication_router(
    *,
    publish_handler: PublishDiscoverySupplyHandler,
    revoke_handler: RevokeDiscoveryPublicationHandler,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter(prefix="/publications", tags=["operations"])

    async def actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def publish(
        body: DiscoveryPublicationBody,
        key: IdempotencyKey,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> object:
        return await publish_discovery_supply(
            publish_handler,
            PublishDiscoverySupplyCommand(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                idempotency_key=key,
                **body.model_dump(),
            ),
        )

    async def revoke(
        publication_id: UUID,
        body: RevokeDiscoveryConfigurationBody,
        key: IdempotencyKey,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> object:
        return await revoke_discovery_publication(
            revoke_handler,
            RevokeDiscoveryPublicationCommand(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                authority_party_id=body.authority_party_id,
                publication_id=publication_id,
                expected_revision=body.expected_revision,
                idempotency_key=key,
            ),
        )

    router.add_api_route("", publish, methods=["POST"])
    router.add_api_route("/{publication_id}/revoke", revoke, methods=["POST"])
    return router
