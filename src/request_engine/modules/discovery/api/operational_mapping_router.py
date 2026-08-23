from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from request_engine.modules.discovery.api.operational_models import (
    OfferingClassificationBody,
    RevokeDiscoveryConfigurationBody,
)
from request_engine.modules.discovery.application.commands.mapping import (
    MapOfferingHandler,
    MapOfferingToServiceClassificationCommand,
    map_offering_to_service_classification,
)
from request_engine.modules.discovery.application.commands.revoke_mapping import (
    RevokeOfferingMappingHandler,
    RevokeOfferingServiceClassificationCommand,
    revoke_offering_service_classification,
)
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver

from .operational_router_types import IdempotencyKey


def create_mapping_router(
    *,
    mapping_handler: MapOfferingHandler,
    revoke_mapping_handler: RevokeOfferingMappingHandler,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter(prefix="/offerings", tags=["operations"])

    async def actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

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

    async def revoke_mapping(
        offering_id: UUID,
        body: RevokeDiscoveryConfigurationBody,
        key: IdempotencyKey,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> object:
        return await revoke_offering_service_classification(
            revoke_mapping_handler,
            RevokeOfferingServiceClassificationCommand(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                authority_party_id=body.authority_party_id,
                offering_id=offering_id,
                expected_revision=body.expected_revision,
                idempotency_key=key,
            ),
        )

    router.add_api_route(
        "/{offering_id}/classification",
        map_offering,
        methods=["PUT"],
    )
    router.add_api_route(
        "/{offering_id}/classification/revoke",
        revoke_mapping,
        methods=["POST"],
    )
    return router
