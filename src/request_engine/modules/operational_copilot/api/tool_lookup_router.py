from collections.abc import Callable
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from request_engine.modules.booking.contracts.copilot import CopilotBookingReader
from request_engine.modules.catalog.contracts.copilot import CopilotCatalogReader
from request_engine.modules.operational_copilot.api.tool_lookup_models import (
    AssignmentDayEndView,
    LocationClockView,
    OfferingCandidateView,
    QueueCandidateView,
    ResourceCandidateView,
)
from request_engine.modules.queue.contracts.copilot import CopilotQueueReader
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, require_capability


def create_tool_lookup_router(
    *,
    actor_resolver: ActorResolver,
    booking_reader: CopilotBookingReader,
    catalog_reader: CopilotCatalogReader,
    queue_reader: CopilotQueueReader,
) -> APIRouter:
    router = APIRouter(prefix="/v1/operational-copilot/tools", tags=["operational-copilot-tools"])

    async def actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def resources(
        current: Annotated[ActorContext, Depends(actor)],
        reference: Annotated[str, Query(min_length=1, max_length=250)],
    ) -> list[ResourceCandidateView]:
        require_capability(current, "operational_copilot.interpret")
        matches = await booking_reader.find_resources(
            organization_id=current.organization_id,
            reference=reference,
        )
        return [ResourceCandidateView.from_match(value) for value in matches]

    async def offerings(
        current: Annotated[ActorContext, Depends(actor)],
        reference: Annotated[str, Query(min_length=1, max_length=250)],
    ) -> list[OfferingCandidateView]:
        require_capability(current, "operational_copilot.interpret")
        matches = await catalog_reader.find_offerings(
            organization_id=current.organization_id,
            reference=reference,
        )
        return [OfferingCandidateView.from_match(value) for value in matches]

    async def queues(current: Annotated[ActorContext, Depends(actor)]) -> list[QueueCandidateView]:
        require_capability(current, "operational_copilot.interpret")
        matches = await queue_reader.list_queues(organization_id=current.organization_id)
        return [QueueCandidateView.from_match(value) for value in matches]

    async def location_clock(
        location_id: UUID,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> LocationClockView:
        require_capability(current, "operational_copilot.interpret")
        value = await catalog_reader.read_location_clock(
            organization_id=current.organization_id,
            location_id=location_id,
        )
        if value is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="location not found")
        return LocationClockView.from_clock(value)

    async def assignment_day_end(
        assignment_id: UUID,
        current: Annotated[ActorContext, Depends(actor)],
        weekday: Annotated[int, Query(ge=0, le=6)],
    ) -> AssignmentDayEndView:
        require_capability(current, "operational_copilot.interpret")
        day_end = await booking_reader.read_assignment_day_end(
            organization_id=current.organization_id,
            assignment_id=assignment_id,
            weekday=weekday,
        )
        return AssignmentDayEndView(assignment_id=assignment_id, weekday=weekday, day_end=day_end)

    _add(router, "/resources", resources, list[ResourceCandidateView], "copilot_lookup_resources")
    _add(router, "/offerings", offerings, list[OfferingCandidateView], "copilot_lookup_offerings")
    _add(router, "/queues", queues, list[QueueCandidateView], "copilot_list_queues")
    _add(router, "/locations/{location_id}/clock", location_clock, LocationClockView, "copilot_location_clock")
    _add(router, "/assignments/{assignment_id}/day-end", assignment_day_end, AssignmentDayEndView, "copilot_assignment_day_end")
    return router


def _add(
    router: APIRouter,
    path: str,
    endpoint: Callable[..., Any],
    response_model: Any,
    operation_id: str,
) -> None:
    add_capability_route(
        router,
        path,
        endpoint,
        capability="operational_copilot.interpret",
        methods=["GET"],
        operation_id=operation_id,
        response_model=response_model,
    )
