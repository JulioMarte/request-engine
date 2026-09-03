from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, status
from pydantic import BaseModel, ConfigDict, Field

from request_engine.modules.booking.api.operational_assignment_models import (
    AvailabilityWindowBody,
)
from request_engine.modules.booking.application.commands.create_resource import (
    CreateResourceCommand,
    CreateResourceHandler,
    create_resource,
)
from request_engine.modules.booking.application.commands.set_resource_location_availability import (
    ResourceLocationAvailabilityWindow,
)
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, require_capability

IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=1, max_length=250),
]


class CreateResourceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    authority_party_id: UUID
    location_id: UUID
    resource_key: str = Field(min_length=1, max_length=160)
    display_name: str = Field(min_length=1, max_length=200)
    capacity_model: Literal["exclusive", "units"] = "exclusive"
    capacity_units: int = Field(default=1, ge=1)
    capability_ids: tuple[UUID, ...] = ()
    weekly_availability: tuple[AvailabilityWindowBody, ...] = ()


def create_resource_bootstrap_router(
    *,
    handler: CreateResourceHandler,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter(prefix="/v1/booking/resources", tags=["booking-configuration"])

    async def actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def create(
        body: CreateResourceBody,
        idempotency_key: IdempotencyKey,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> object:
        require_capability(current, "booking.manage_supply")
        return await create_resource(
            handler,
            CreateResourceCommand(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                authority_party_id=body.authority_party_id,
                location_id=body.location_id,
                resource_key=body.resource_key,
                display_name=body.display_name,
                capacity_model=body.capacity_model,
                capacity_units=body.capacity_units,
                capability_ids=body.capability_ids,
                weekly_availability=tuple(
                    ResourceLocationAvailabilityWindow(
                        weekday=item.weekday,
                        local_start=item.local_start,
                        local_end=item.local_end,
                        valid_from=item.valid_from,
                        valid_until=item.valid_until,
                    )
                    for item in body.weekly_availability
                ),
                idempotency_key=idempotency_key,
            ),
        )

    add_capability_route(
        router,
        "",
        create,
        capability="booking.manage_supply",
        methods=["POST"],
        status_code=status.HTTP_201_CREATED,
    )
    return router
