from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request

from request_engine.modules.queue.api.same_day_selection_models import (
    RecallHoldBody,
    RecallHoldView,
    ReleaseRecallHoldBody,
)
from request_engine.modules.queue.application.commands.recall_hold import (
    RecallHoldCommand,
    RecallHoldExecutor,
)
from request_engine.modules.queue.application.commands.release_recall_hold import (
    ReleaseRecallHoldCommand,
    ReleaseRecallHoldExecutor,
)
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, require_capability

IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=1, max_length=250),
]


def create_same_day_hold_router(
    *,
    recall_hold_executor: RecallHoldExecutor,
    release_hold_executor: ReleaseRecallHoldExecutor,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter()

    async def actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def recall_hold_entry(
        queue_id: UUID,
        queue_entry_id: UUID,
        body: RecallHoldBody,
        current: Annotated[ActorContext, Depends(actor)],
        idempotency_key: IdempotencyKey,
    ) -> RecallHoldView:
        require_capability(current, "queue.recall_hold")
        hold = await recall_hold_executor.recall_hold(
            RecallHoldCommand(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                queue_id=queue_id,
                queue_entry_id=queue_entry_id,
                expected_revision=body.expected_revision,
                kind=body.kind,
                release_at=body.release_at,
                reason=body.reason,
                idempotency_key=idempotency_key,
            )
        )
        return RecallHoldView.from_contract(hold)

    async def release_hold(
        queue_id: UUID,
        queue_entry_id: UUID,
        body: ReleaseRecallHoldBody,
        current: Annotated[ActorContext, Depends(actor)],
        idempotency_key: IdempotencyKey,
    ) -> RecallHoldView | None:
        require_capability(current, "queue.release_recall_hold")
        hold = await release_hold_executor.release_recall_hold(
            ReleaseRecallHoldCommand(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                queue_id=queue_id,
                queue_entry_id=queue_entry_id,
                hold_id=body.hold_id,
                expected_revision=body.expected_revision,
                idempotency_key=idempotency_key,
            )
        )
        return RecallHoldView.from_contract(hold) if hold is not None else None

    add_capability_route(
        router,
        "/queues/{queue_id}/entries/{queue_entry_id}/recall-hold",
        recall_hold_entry,
        capability="queue.recall_hold",
        methods=["POST"],
        response_model=RecallHoldView,
    )
    add_capability_route(
        router,
        "/queues/{queue_id}/entries/{queue_entry_id}/recall-hold/release",
        release_hold,
        capability="queue.release_recall_hold",
        methods=["POST"],
        response_model=RecallHoldView | None,
    )
    return router
