from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel

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


class LocationBody(BaseModel):
    authority_party_id: UUID
    location_key: str
    display_name: str
    timezone: str
    active: bool = True
    address_line1: str | None = None
    address_line2: str | None = None
    locality: str | None = None
    administrative_area: str | None = None
    postal_code: str | None = None
    country_code: str | None = None
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    geocoding_source: str | None = None
    geocoded_at: datetime | None = None


class LocationUpdateBody(BaseModel):
    authority_party_id: UUID
    timezone: str
    active: bool
    expected_operational_revision: int
    address_line1: str | None = None
    address_line2: str | None = None
    locality: str | None = None
    administrative_area: str | None = None
    postal_code: str | None = None
    country_code: str | None = None
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    geocoding_source: str | None = None
    geocoded_at: datetime | None = None


class ContactBody(BaseModel):
    channel: Literal["phone", "whatsapp", "email"]
    value: str
    label: str | None = None


class LocationContactsBody(BaseModel):
    authority_party_id: UUID
    contacts: tuple[ContactBody, ...]


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
        payload = body.model_dump()
        return await create_location(
            create_handler,
            CreateLocationCommand(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                idempotency_key=key,
                **payload,
            ),
        )

    @router.patch("/{location_id}")
    async def update(
        location_id: UUID,
        body: LocationUpdateBody,
        key: IdempotencyKey,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> object:
        payload = body.model_dump()
        return await update_location_operational_info(
            update_handler,
            UpdateLocationOperationalInfoCommand(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                location_id=location_id,
                idempotency_key=key,
                **payload,
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
