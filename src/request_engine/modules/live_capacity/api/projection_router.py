from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from request_engine.modules.live_capacity.adapters.db.live_capacity_reader import (
    PostgresLiveCapacityReader,
)
from request_engine.modules.live_capacity.api.projection_models import (
    StaffLiveCapacityProjectionView,
)
from request_engine.modules.live_capacity.application.queries.projection import (
    ReadStaffLiveCapacityQuery,
)
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, require_capability


def create_projection_router(
    reader: PostgresLiveCapacityReader,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter()

    async def actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def read_projection(
        service_queue_id: UUID,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> StaffLiveCapacityProjectionView:
        require_capability(current, "live_capacity.read")
        projection = await reader.staff_projection(
            ReadStaffLiveCapacityQuery(
                organization_id=current.organization_id,
                service_queue_id=service_queue_id,
            )
        )
        return StaffLiveCapacityProjectionView.from_contract(projection)

    add_capability_route(
        router,
        "/live-capacity/queues/{service_queue_id}",
        read_projection,
        capability="live_capacity.read",
        methods=["GET"],
        response_model=StaffLiveCapacityProjectionView,
    )
    return router
