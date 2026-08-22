from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request

from request_engine.modules.booking.api.operational_assignment_models import (
    AssignmentBody,
    AvailabilityBody,
    RetireAssignmentBody,
)
from request_engine.modules.booking.application.commands import (
    retire_resource_location_assignment as retire_assignment,
)
from request_engine.modules.booking.application.commands.assign_resource_to_location import (
    AssignResourceToLocationCommand,
    AssignResourceToLocationHandler,
    assign_resource_to_location,
)
from request_engine.modules.booking.application.commands.set_resource_location_availability import (
    ResourceLocationAvailabilityWindow,
    SetResourceLocationAvailabilityCommand,
    SetResourceLocationAvailabilityHandler,
    set_resource_location_availability,
)
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver

IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=1, max_length=250),
]


def create_operational_assignment_router(
    *,
    assign_handler: AssignResourceToLocationHandler,
    retire_handler: retire_assignment.RetireResourceLocationAssignmentHandler,
    availability_handler: SetResourceLocationAvailabilityHandler,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter(
        prefix="/v1/operations/resource-assignments",
        tags=["operations"],
    )

    async def actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def assign(
        body: AssignmentBody,
        key: IdempotencyKey,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> object:
        command = AssignResourceToLocationCommand(
            organization_id=current.organization_id,
            principal_id=current.principal_id,
            authority_party_id=body.authority_party_id,
            resource_id=body.resource_id,
            location_id=body.location_id,
            effective_from=body.effective_from,
            effective_until=body.effective_until,
            expected_resource_availability_revision=(body.expected_resource_availability_revision),
            idempotency_key=key,
        )
        return await assign_resource_to_location(assign_handler, command)

    async def retire(
        assignment_id: UUID,
        body: RetireAssignmentBody,
        key: IdempotencyKey,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> object:
        command = retire_assignment.RetireResourceLocationAssignmentCommand(
            organization_id=current.organization_id,
            principal_id=current.principal_id,
            authority_party_id=body.authority_party_id,
            assignment_id=assignment_id,
            retired_at=body.retired_at,
            expected_assignment_revision=body.expected_assignment_revision,
            expected_resource_availability_revision=(body.expected_resource_availability_revision),
            idempotency_key=key,
        )
        return await retire_assignment.retire_resource_location_assignment(
            retire_handler,
            command,
        )

    async def availability(
        assignment_id: UUID,
        body: AvailabilityBody,
        key: IdempotencyKey,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> object:
        windows = tuple(
            ResourceLocationAvailabilityWindow(
                weekday=item.weekday,
                local_start=item.local_start,
                local_end=item.local_end,
                valid_from=item.valid_from,
                valid_until=item.valid_until,
            )
            for item in body.windows
        )
        command = SetResourceLocationAvailabilityCommand(
            organization_id=current.organization_id,
            principal_id=current.principal_id,
            authority_party_id=body.authority_party_id,
            assignment_id=assignment_id,
            windows=windows,
            expected_resource_availability_revision=(body.expected_resource_availability_revision),
            idempotency_key=key,
        )
        return await set_resource_location_availability(availability_handler, command)

    router.add_api_route("", assign, methods=["POST"])
    router.add_api_route("/{assignment_id}/retire", retire, methods=["POST"])
    router.add_api_route("/{assignment_id}/availability", availability, methods=["PUT"])
    return router
