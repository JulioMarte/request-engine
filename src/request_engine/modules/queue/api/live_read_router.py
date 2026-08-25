from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from request_engine.modules.queue.adapters.db.live_queue_reader import PostgresLiveQueueReader
from request_engine.modules.queue.api.live_history_models import StaffQueueHistoryPageView
from request_engine.modules.queue.api.live_models import StaffQueueEntryView
from request_engine.modules.queue.api.workload_models import WorkloadClassificationView
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

    async def staff_history(
        queue_id: UUID,
        window_start: Annotated[datetime, Query()],
        window_end: Annotated[datetime, Query()],
        current: Annotated[ActorContext, Depends(actor)],
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        cursor: Annotated[UUID | None, Query()] = None,
    ) -> StaffQueueHistoryPageView:
        require_capability(current, "queue.staff_read")
        if window_end <= window_start:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="window_end must be after window_start",
            )
        page = await reader.staff_queue_history(
            current.organization_id,
            queue_id,
            window_start=window_start,
            window_end=window_end,
            limit=limit,
            cursor=cursor,
        )
        return StaffQueueHistoryPageView.from_contract(page)

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
        "/queues/{queue_id}/staff/history",
        staff_history,
        capability="queue.staff_read",
        methods=["GET"],
        response_model=StaffQueueHistoryPageView,
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
