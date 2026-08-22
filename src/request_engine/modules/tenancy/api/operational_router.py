from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel

from request_engine.modules.tenancy.application.commands.set_organization_public_contacts import (
    OrganizationPublicContactInput,
    SetOrganizationPublicContactsCommand,
    SetOrganizationPublicContactsHandler,
    set_organization_public_contacts,
)
from request_engine.modules.tenancy.application.commands.update_organization_operational_profile import (
    UpdateOrganizationOperationalProfileCommand,
    UpdateOrganizationOperationalProfileHandler,
    update_organization_operational_profile,
)
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver

IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=250)]


class OrganizationProfileBody(BaseModel):
    authority_party_id: UUID
    legal_name: str | None = None
    default_timezone: str | None = None
    default_locale: str | None = None
    default_currency: str | None = None
    operational_status: str = "active"


class PublicContactBody(BaseModel):
    channel: str
    value: str
    label: str | None = None


class OrganizationContactsBody(BaseModel):
    authority_party_id: UUID
    contacts: tuple[PublicContactBody, ...]


def create_operational_router(
    *,
    profile_handler: UpdateOrganizationOperationalProfileHandler,
    contacts_handler: SetOrganizationPublicContactsHandler,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter(prefix="/v1/operations/organization", tags=["operations"])

    async def actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    @router.patch("/profile")
    async def update_profile(
        body: OrganizationProfileBody,
        idempotency_key: IdempotencyKey,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> object:
        return await update_organization_operational_profile(
            profile_handler,
            UpdateOrganizationOperationalProfileCommand(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                authority_party_id=body.authority_party_id,
                legal_name=body.legal_name,
                default_timezone=body.default_timezone,
                default_locale=body.default_locale,
                default_currency=body.default_currency,
                operational_status=body.operational_status,
                idempotency_key=idempotency_key,
            ),
        )

    @router.put("/contacts")
    async def set_contacts(
        body: OrganizationContactsBody,
        idempotency_key: IdempotencyKey,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> object:
        contacts = tuple(
            OrganizationPublicContactInput(item.channel, item.value, item.label)
            for item in body.contacts
        )
        return await set_organization_public_contacts(
            contacts_handler,
            SetOrganizationPublicContactsCommand(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                authority_party_id=body.authority_party_id,
                contacts=contacts,
                idempotency_key=idempotency_key,
            ),
        )

    return router
