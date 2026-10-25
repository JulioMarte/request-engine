"""Owner HTTP surface for renaming a Resource and replacing its capabilities."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from request_engine.modules.booking.application.commands import (
    replace_resource_capabilities as replace_command,
)
from request_engine.modules.booking.application.commands import (
    update_resource as update_command,
)
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, require_capability

IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=1, max_length=250),
]


class ResourceUpdateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    authority_party_id: UUID
    display_name: str = Field(min_length=1, max_length=200)
    expected_resource_availability_revision: int = Field(gt=0)

    @field_validator("display_name")
    @classmethod
    def label(cls, value: str) -> str:
        return update_command.normalize_resource_display_name(value)


class ResourceCapabilitiesBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    authority_party_id: UUID
    capability_ids: tuple[UUID, ...] = Field(max_length=replace_command.MAX_RESOURCE_CAPABILITIES)
    expected_resource_availability_revision: int = Field(gt=0)

    @field_validator("capability_ids")
    @classmethod
    def unique(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        replace_command.validate_capability_ids(value)
        return value


class ResourceUpdateView(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)
    resource_id: UUID
    resource_key: str
    display_name: str
    active: bool
    availability_revision: int


class ResourceCapabilitiesView(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)
    resource_id: UUID
    capability_ids: tuple[UUID, ...]
    added_capability_ids: tuple[UUID, ...]
    removed_capability_ids: tuple[UUID, ...]
    retained_commitment_count: int = Field(
        description=(
            "Confirmed future Reservations that keep their CapacityClaims on this Resource "
            "although they rely on a removed capability; they are not cancelled or moved."
        )
    )
    availability_revision: int


def create_resource_configuration_router(
    *,
    update_handler: update_command.UpdateResourceHandler,
    capabilities_handler: replace_command.ReplaceResourceCapabilitiesHandler,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter(prefix="/v1/operations/resources", tags=["operations"])

    async def actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def update(
        resource_id: UUID,
        body: ResourceUpdateBody,
        key: IdempotencyKey,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> ResourceUpdateView:
        require_capability(current, "booking.manage_supply")
        result = await update_command.update_resource(
            update_handler,
            update_command.UpdateResourceCommand(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                resource_id=resource_id,
                idempotency_key=key,
                **body.model_dump(),
            ),
        )
        return ResourceUpdateView.model_validate(result)

    async def replace(
        resource_id: UUID,
        body: ResourceCapabilitiesBody,
        key: IdempotencyKey,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> ResourceCapabilitiesView:
        require_capability(current, "booking.manage_supply")
        result = await replace_command.replace_resource_capabilities(
            capabilities_handler,
            replace_command.ReplaceResourceCapabilitiesCommand(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                authority_party_id=body.authority_party_id,
                resource_id=resource_id,
                capability_ids=body.capability_ids,
                expected_resource_availability_revision=(
                    body.expected_resource_availability_revision
                ),
                idempotency_key=key,
            ),
        )
        return ResourceCapabilitiesView.model_validate(result)

    add_capability_route(
        router,
        "/{resource_id}",
        update,
        methods=["PATCH"],
        capability="booking.manage_supply",
        operation_id="booking_resource_update",
        owner="booking",
        response_model=ResourceUpdateView,
    )
    add_capability_route(
        router,
        "/{resource_id}/capabilities",
        replace,
        methods=["PUT"],
        capability="booking.manage_supply",
        operation_id="booking_resource_capabilities_replace",
        owner="booking",
        response_model=ResourceCapabilitiesView,
    )
    return router
