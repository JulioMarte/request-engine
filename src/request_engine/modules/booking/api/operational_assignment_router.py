from datetime import date, datetime, time
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel

from request_engine.modules.booking.application.commands.assign_resource_to_location import (
    AssignResourceToLocationCommand,
    AssignResourceToLocationHandler,
    assign_resource_to_location,
)
from request_engine.modules.booking.application.commands.retire_resource_location_assignment import (
    RetireResourceLocationAssignmentCommand,
    RetireResourceLocationAssignmentHandler,
    retire_resource_location_assignment,
)
from request_engine.modules.booking.application.commands.set_resource_location_availability import (
    ResourceLocationAvailabilityWindow,
    SetResourceLocationAvailabilityCommand,
    SetResourceLocationAvailabilityHandler,
    set_resource_location_availability,
)
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver

IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=250)]


class AssignmentBody(BaseModel):
    authority_party_id: UUID
    resource_id: UUID
    location_id: UUID
    effective_from: datetime
    effective_until: datetime | None = None
    expected_resource_availability_revision: int


class RetireAssignmentBody(BaseModel):
    authority_party_id: UUID
    retired_at: datetime
    expected_assignment_revision: int
    expected_resource_availability_revision: int


class AvailabilityWindowBody(BaseModel):
    weekday: int
    local_start: time
    local_end: time
    valid_from: date | None = None
    valid_until: date | None = None


class AvailabilityBody(BaseModel):
    authority_party_id: UUID
    expected_resource_availability_revision: int
    windows: tuple[AvailabilityWindowBody, ...]


def create_operational_assignment_router(
    *,
    assign_handler: AssignResourceToLocationHandler,
    retire_handler: RetireResourceLocationAssignmentHandler,
    availability_handler: SetResourceLocationAvailabilityHandler,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter(prefix="/v1/operations/resource-assignments", tags=["operations"])

    async def actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    @router.post("")
    async def assign(
        body: AssignmentBody,
        key: IdempotencyKey,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> object:
        return await assign_resource_to_location(
            assign_handler,
            AssignResourceToLocationCommand(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                idempotency_key=key,
                **body.model_dump(),
            ),
        )

    @router.post("/{assignment_id}/retire")
    async def retire(
        assignment_id: UUID,
        body: RetireAssignmentBody,
        key: IdempotencyKey,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> object:
        return await retire_resource_location_assignment(
            retire_handler,
            RetireResourceLocationAssignmentCommand(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                assignment_id=assignment_id,
                idempotency_key=key,
                **body.model_dump(),
            ),
        )

    @router.put("/{assignment_id}/availability")
    async def availability(
        assignment_id: UUID,
        body: AvailabilityBody,
        key: IdempotencyKey,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> object:
        windows = tuple(
            ResourceLocationAvailabilityWindow(**item.model_dump()) for item in body.windows
        )
        return await set_resource_location_availability(
            availability_handler,
            SetResourceLocationAvailabilityCommand(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                authority_party_id=body.authority_party_id,
                assignment_id=assignment_id,
                windows=windows,
                expected_resource_availability_revision=(
                    body.expected_resource_availability_revision
                ),
                idempotency_key=key,
            ),
        )

    return router
