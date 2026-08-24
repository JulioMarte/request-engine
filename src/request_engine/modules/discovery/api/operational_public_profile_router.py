from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from request_engine.modules.discovery.api.operational_models import (
    DeactivateResourcePublicProfileBody,
    ResourcePublicProfileBody,
)
from request_engine.modules.discovery.application.commands.public_profile import (
    DeactivateResourcePublicProfileCommand,
    ResourcePublicProfileHandler,
    SetResourcePublicProfileCommand,
    deactivate_resource_public_profile,
    set_resource_public_profile,
)
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver

from .operational_router_types import IdempotencyKey


def create_public_profile_router(
    *,
    handler: ResourcePublicProfileHandler,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter(prefix="/resources", tags=["operations"])

    async def actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def set_profile(
        resource_id: UUID,
        body: ResourcePublicProfileBody,
        key: IdempotencyKey,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> object:
        return await set_resource_public_profile(
            handler,
            SetResourcePublicProfileCommand(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                resource_id=resource_id,
                idempotency_key=key,
                **body.model_dump(),
            ),
        )

    async def deactivate_profile(
        resource_id: UUID,
        body: DeactivateResourcePublicProfileBody,
        key: IdempotencyKey,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> object:
        return await deactivate_resource_public_profile(
            handler,
            DeactivateResourcePublicProfileCommand(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                resource_id=resource_id,
                idempotency_key=key,
                **body.model_dump(),
            ),
        )

    router.add_api_route("/{resource_id}/public-profile", set_profile, methods=["PUT"])
    router.add_api_route(
        "/{resource_id}/public-profile/deactivate", deactivate_profile, methods=["POST"]
    )
    return router
