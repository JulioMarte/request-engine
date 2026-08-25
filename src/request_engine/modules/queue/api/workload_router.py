from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, status

from request_engine.modules.queue.adapters.db.live_queue_commands import PostgresLiveQueueCommands
from request_engine.modules.queue.api.workload_models import (
    CreateWorkloadClassificationBody,
    DeactivateWorkloadClassificationBody,
    UpdateWorkloadClassificationBody,
    WorkloadClassificationView,
)
from request_engine.modules.queue.application.live_commands import (
    CreateWorkloadClassificationCommand,
    DeactivateWorkloadClassificationCommand,
    UpdateWorkloadClassificationCommand,
)
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, require_capability

IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=1, max_length=250),
]


def create_workload_router(
    commands: PostgresLiveQueueCommands,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter()

    async def actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def create_workload(
        body: CreateWorkloadClassificationBody,
        current: Annotated[ActorContext, Depends(actor)],
        idempotency_key: IdempotencyKey,
    ) -> WorkloadClassificationView:
        require_capability(current, "workload.manage")
        item = await commands.create_workload(
            CreateWorkloadClassificationCommand(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                workload_key=body.workload_key,
                display_name=body.display_name,
                idempotency_key=idempotency_key,
            )
        )
        return WorkloadClassificationView.from_contract(item)

    async def update_workload(
        workload_id: UUID,
        body: UpdateWorkloadClassificationBody,
        current: Annotated[ActorContext, Depends(actor)],
        idempotency_key: IdempotencyKey,
    ) -> WorkloadClassificationView:
        require_capability(current, "workload.manage")
        item = await commands.update_workload(
            UpdateWorkloadClassificationCommand(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                workload_id=workload_id,
                display_name=body.display_name,
                expected_revision=body.expected_revision,
                idempotency_key=idempotency_key,
            )
        )
        return WorkloadClassificationView.from_contract(item)

    async def deactivate_workload(
        workload_id: UUID,
        body: DeactivateWorkloadClassificationBody,
        current: Annotated[ActorContext, Depends(actor)],
        idempotency_key: IdempotencyKey,
    ) -> WorkloadClassificationView:
        require_capability(current, "workload.manage")
        item = await commands.deactivate_workload(
            DeactivateWorkloadClassificationCommand(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                workload_id=workload_id,
                expected_revision=body.expected_revision,
                idempotency_key=idempotency_key,
            )
        )
        return WorkloadClassificationView.from_contract(item)

    add_capability_route(
        router,
        "/live-workloads",
        create_workload,
        capability="workload.manage",
        methods=["POST"],
        response_model=WorkloadClassificationView,
        status_code=status.HTTP_201_CREATED,
    )
    add_capability_route(
        router,
        "/live-workloads/{workload_id}/update",
        update_workload,
        capability="workload.manage",
        methods=["POST"],
        response_model=WorkloadClassificationView,
    )
    add_capability_route(
        router,
        "/live-workloads/{workload_id}/deactivate",
        deactivate_workload,
        capability="workload.manage",
        methods=["POST"],
        response_model=WorkloadClassificationView,
    )
    return router
