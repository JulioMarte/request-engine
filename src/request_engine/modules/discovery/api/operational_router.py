from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request

from request_engine.modules.discovery.api.operational_models import (
    DiscoveryPublicationBody,
    OfferingClassificationBody,
    RevokeDiscoveryPublicationBody,
)
from request_engine.modules.discovery.application.commands.mapping import (
    MapOfferingHandler,
    MapOfferingToServiceClassificationCommand,
    map_offering_to_service_classification,
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

IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=1, max_length=250),
]


def create_operational_router(
    *,
    mapping_handler: MapOfferingHandler,
    publish_handler: PublishDiscoverySupplyHandler,
    revoke_handler: RevokeDiscoveryPublicationHandler,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter(prefix="/v1/operations/discovery", tags=["operations"])

    async def actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    @router.put("/offerings/{offering_id}/classification")
    async def map_offering(
        offering_id: UUID,
        body: OfferingClassificationBody,
        key: IdempotencyKey,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> object:
        return await map_offering_to_service_classification(
            mapping_handler,
            MapOfferingToServiceClassificationCommand(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                authority_party_id=body.authority_party_id,
                offering_id=offering_id,
                classification_key=body.classification_key,
                idempotency_key=key,
                expected_revision=body.expected_revision,
            ),
        )

    @router.post("/publications")
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

    @router.post("/publications/{publication_id}/revoke")
    async def revoke(
        publication_id: UUID,
        body: RevokeDiscoveryPublicationBody,
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

    return router
