from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request

from request_engine.modules.catalog.api.operational_profile_models import (
    LocationBody,
    LocationContactsBody,
    LocationUpdateBody,
)
from request_engine.modules.catalog.application.commands.create_location import (
    CreateLocationCommand,
    CreateLocationHandler,
    create_location,
)
from request_engine.modules.catalog.application.commands.set_location_public_contacts import (
    LocationPublicContactInput,
    SetLocationPublicContactsCommand,
    SetLocationPublicContactsHandler,
    set_location_public_contacts,
)
from request_engine.modules.catalog.application.commands.update_location_operational_info import (
    UpdateLocationOperationalInfoCommand,
    UpdateLocationOperationalInfoHandler,
    update_location_operational_info,
)
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver

IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=1, max_length=250),
]


def create_operational_profile_router(
    *,
    create_handler: CreateLocationHandler,
    update_handler: UpdateLocationOperationalInfoHandler,
    contacts_handler: SetLocationPublicContactsHandler,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter(prefix="/v1/operations/locations", tags=["operations"])

    async def actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    @router.post("")
    async def create(
        body: LocationBody,
        key: IdempotencyKey,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> object:
        return await create_location(
            create_handler,
            CreateLocationCommand(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                idempotency_key=key,
                **body.model_dump(),
            ),
        )

    @router.patch("/{location_id}")
    async def update(
        location_id: UUID,
        body: LocationUpdateBody,
        key: IdempotencyKey,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> object:
        return await update_location_operational_info(
            update_handler,
            UpdateLocationOperationalInfoCommand(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                location_id=location_id,
                idempotency_key=key,
                **body.model_dump(),
            ),
        )

    @router.put("/{location_id}/contacts")
    async def contacts(
        location_id: UUID,
        body: LocationContactsBody,
        key: IdempotencyKey,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> object:
        values = tuple(
            LocationPublicContactInput(item.channel, item.value, item.label)
            for item in body.contacts
        )
        return await set_location_public_contacts(
            contacts_handler,
            SetLocationPublicContactsCommand(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                authority_party_id=body.authority_party_id,
                location_id=location_id,
                contacts=values,
                idempotency_key=key,
            ),
        )

    return router
