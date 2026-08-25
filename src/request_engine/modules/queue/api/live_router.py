from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, status

from request_engine.modules.queue.api.live_models import (
    CheckInBody,
    LiveQueueEntryView,
    MarkNoShowBody,
    StaffQueueEntryView,
    WorkloadClassificationView,
)
from request_engine.modules.queue.application.live_commands import CheckInCommand, MarkNoShowCommand
from request_engine.modules.queue.adapters.db.live_queue_commands import PostgresLiveQueueCommands
from request_engine.modules.queue.adapters.db.live_queue_reader import PostgresLiveQueueReader
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, require_capability

IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=250)]


def create_live_router(
    *,
    commands: PostgresLiveQueueCommands,
    reader: PostgresLiveQueueReader,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["live-queues"])

    async def actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def check_in(
        queue_id: UUID,
        body: CheckInBody,
        current: Annotated[ActorContext, Depends(actor)],
        idempotency_key: IdempotencyKey,
    ) -> LiveQueueEntryView:
        require_capability(current, "queue.check_in")
        result = await commands.check_in(
            CheckInCommand(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                queue_id=queue_id,
                subject_party_id=body.subject_party_id,
                reservation_id=body.reservation_id,
                offering_id=body.offering_id,
                expected_workload_classification_id=body.expected_workload_classification_id,
                idempotency_key=idempotency_key,
            )
        )
        return LiveQueueEntryView.from_contract(result)

    async def mark_no_show(
        queue_entry_id: UUID,
        body: MarkNoShowBody,
        current: Annotated[ActorContext, Depends(actor)],
        idempotency_key: IdempotencyKey,
    ) -> LiveQueueEntryView:
        require_capability(current, "queue.mark_no_show")
        result = await commands.mark_no_show(
            MarkNoShowCommand(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                queue_entry_id=queue_entry_id,
                expected_revision=body.expected_revision,
                idempotency_key=idempotency_key,
            )
        )
        return LiveQueueEntryView.from_contract(result)

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
        router, "/queues/{queue_id}/check-in", check_in,
        capability="queue.check_in", methods=["POST"],
        response_model=LiveQueueEntryView, status_code=status.HTTP_201_CREATED,
    )
    add_capability_route(
        router, "/queue-entries/{queue_entry_id}/no-show", mark_no_show,
        capability="queue.mark_no_show", methods=["POST"], response_model=LiveQueueEntryView,
    )
    add_capability_route(
        router, "/queues/{queue_id}/staff", staff_queue,
        capability="queue.staff_read", methods=["GET"],
        response_model=tuple[StaffQueueEntryView, ...],
    )
    add_capability_route(
        router, "/live-workloads", workloads,
        capability="workload.list", methods=["GET"],
        response_model=tuple[WorkloadClassificationView, ...],
    )
    return router
