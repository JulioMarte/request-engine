from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, status
from pydantic import BaseModel, ConfigDict, Field

from request_engine.modules.catalog.application.commands.bootstrap_catalog import (
    CatalogBootstrapHandler,
    CreateOfferingCommand,
    CreateResourceCapabilityCommand,
    OfferingRequirementInput,
    create_offering,
    create_resource_capability,
)
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver

IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=1, max_length=250),
]


class ResourceCapabilityBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    authority_party_id: UUID
    capability_key: str = Field(min_length=1, max_length=160)
    display_name: str = Field(min_length=1, max_length=200)


class OfferingRequirementBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capability_id: UUID
    quantity: int = Field(default=1, ge=1)


class OfferingBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    authority_party_id: UUID
    offering_key: str = Field(min_length=1, max_length=160)
    display_name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    duration_minutes: int = Field(gt=0, le=1440)
    bookable: bool = True
    requestable: bool = True
    slot_step_minutes: int = Field(default=30, gt=0, le=1440)
    requirements: tuple[OfferingRequirementBody, ...] = ()


def create_bootstrap_router(
    *,
    handler: CatalogBootstrapHandler,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter(prefix="/v1/catalog", tags=["catalog"])

    async def actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def capability(
        body: ResourceCapabilityBody,
        idempotency_key: IdempotencyKey,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> object:
        return await create_resource_capability(
            handler,
            CreateResourceCapabilityCommand(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                authority_party_id=body.authority_party_id,
                capability_key=body.capability_key,
                display_name=body.display_name,
                idempotency_key=idempotency_key,
            ),
        )

    async def offering(
        body: OfferingBody,
        idempotency_key: IdempotencyKey,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> object:
        return await create_offering(
            handler,
            CreateOfferingCommand(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                authority_party_id=body.authority_party_id,
                offering_key=body.offering_key,
                display_name=body.display_name,
                description=body.description,
                duration_minutes=body.duration_minutes,
                bookable=body.bookable,
                requestable=body.requestable,
                slot_step_minutes=body.slot_step_minutes,
                requirements=tuple(
                    OfferingRequirementInput(item.capability_id, item.quantity)
                    for item in body.requirements
                ),
                idempotency_key=idempotency_key,
            ),
        )

    router.add_api_route(
        "/resource-capabilities",
        capability,
        methods=["POST"],
        status_code=status.HTTP_201_CREATED,
    )
    router.add_api_route(
        "/offerings",
        offering,
        methods=["POST"],
        status_code=status.HTTP_201_CREATED,
    )
    return router
