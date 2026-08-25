from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from request_engine.modules.queue.adapters.db.live_queue_reader import PostgresLiveQueueReader
from request_engine.modules.queue.api.live_models import (
    StaffQueueEntryView,
    WorkloadClassificationView,
)
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, require_capability


def create_live_read_router(
    reader: PostgresLiveQueueReader,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter()

    async def actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def staff_queue(
        queue_id: UUID,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> tuple[StaffQueueEntryView, ...]:
        require_capability(current, "queue.staff_read")
        rows = await reader.staff_queue(current.organization_id, queue_id)
        return tuple(StaffQueueEntryView.from_contract(item) for item in rows)

    async def workloads(
        current: Annotated[ActorContext, Depends(actor)],
    ) -> tuple[WorkloadClassificationView, ...]:
        require_capability(current, "workload.list")
        rows = await reader.workloads(current.organization_id)
        return tuple(WorkloadClassificationView.from_contract(item) for item in rows)

    add_capability_route(
        router,
        "/queues/{queue_id}/staff",
        staff_queue,
        capability="queue.staff_read",
        methods=["GET"],
        response_model=tuple[StaffQueueEntryView, ...],
    )
    add_capability_route(
        router,
        "/live-workloads",
        workloads,
        capability="workload.list",
        methods=["GET"],
        response_model=tuple[WorkloadClassificationView, ...],
    )
    return router
