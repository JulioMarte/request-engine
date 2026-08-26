from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from request_engine.modules.live_capacity.adapters.db.customer_projection_reader import (
    PostgresCustomerLiveCapacityReader,
)
from request_engine.modules.live_capacity.api.customer_projection_models import (
    CustomerLiveCapacityProjectionView,
)
from request_engine.modules.live_capacity.application.queries.customer_projection import (
    ReadCustomerLiveCapacityQuery,
)
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, require_capability


def create_customer_projection_router(
    reader: PostgresCustomerLiveCapacityReader,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter()

    async def actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def read_customer_projection(
        service_queue_id: UUID,
        subject_party_id: Annotated[UUID, Query()],
        current: Annotated[ActorContext, Depends(actor)],
    ) -> CustomerLiveCapacityProjectionView:
        require_capability(current, "live_capacity.customer_read")
        result = await reader.customer_projection(
            ReadCustomerLiveCapacityQuery(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                service_queue_id=service_queue_id,
                subject_party_id=subject_party_id,
                allow_subject_override=current.allows("queue.subject_override"),
            )
        )
        return CustomerLiveCapacityProjectionView.from_contract(result)

    add_capability_route(
        router,
        "/live-capacity/queues/{service_queue_id}/customer",
        read_customer_projection,
        capability="live_capacity.customer_read",
        methods=["GET"],
        response_model=CustomerLiveCapacityProjectionView,
    )
    return router
