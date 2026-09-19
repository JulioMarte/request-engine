from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel

from request_engine.modules.tenancy.application.commands import (
    set_organization_public_contacts as contacts_command,
)
from request_engine.modules.tenancy.application.commands import (
    update_organization_operational_profile as profile_command,
)
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, require_capability

IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=1, max_length=250),
]


class OrganizationProfileBody(BaseModel):
    authority_party_id: UUID
    legal_name: str | None = None
    default_timezone: str | None = None
    default_locale: str | None = None
    default_currency: str | None = None
    operational_status: str = "active"


class PublicContactBody(BaseModel):
    channel: Literal["phone", "whatsapp", "email"]
    value: str
    label: str | None = None


class OrganizationContactsBody(BaseModel):
    authority_party_id: UUID
    contacts: tuple[PublicContactBody, ...]


def create_operational_router(
    *,
    profile_handler: profile_command.UpdateOrganizationOperationalProfileHandler,
    contacts_handler: contacts_command.SetOrganizationPublicContactsHandler,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter(prefix="/v1/operations/organization", tags=["operations"])

    async def actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def update_profile(
        body: OrganizationProfileBody,
        idempotency_key: IdempotencyKey,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> object:
        require_capability(current, "organization.manage_profile")
        command = profile_command.UpdateOrganizationOperationalProfileCommand(
            organization_id=current.organization_id,
            principal_id=current.principal_id,
            authority_party_id=body.authority_party_id,
            legal_name=body.legal_name,
            default_timezone=body.default_timezone,
            default_locale=body.default_locale,
            default_currency=body.default_currency,
            operational_status=body.operational_status,
            idempotency_key=idempotency_key,
        )
        return await profile_command.update_organization_operational_profile(
            profile_handler,
            command,
        )

    async def set_contacts(
        body: OrganizationContactsBody,
        idempotency_key: IdempotencyKey,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> object:
        require_capability(current, "organization.manage_profile")
        contacts = tuple(
            contacts_command.OrganizationPublicContactInput(
                item.channel,
                item.value,
                item.label,
            )
            for item in body.contacts
        )
        command = contacts_command.SetOrganizationPublicContactsCommand(
            organization_id=current.organization_id,
            principal_id=current.principal_id,
            authority_party_id=body.authority_party_id,
            contacts=contacts,
            idempotency_key=idempotency_key,
        )
        return await contacts_command.set_organization_public_contacts(
            contacts_handler,
            command,
        )

    add_capability_route(
        router,
        "/profile",
        update_profile,
        capability="organization.manage_profile",
        methods=["PATCH"],
        operation_id="tenancy_organization_profile_update",
    )
    add_capability_route(
        router,
        "/contacts",
        set_contacts,
        capability="organization.manage_profile",
        methods=["PUT"],
        operation_id="tenancy_organization_contacts_replace",
    )
    return router
