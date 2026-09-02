from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request

from request_engine.modules.queue.adapters.db.same_day_selection_commands import (
    PostgresSameDaySelectionCommands,
)
from request_engine.modules.queue.api.models import QueueEntryView
from request_engine.modules.queue.api.same_day_selection_models import (
    OperatorSelectBody,
    RecallHoldBody,
    RecallHoldView,
    ReleaseRecallHoldBody,
    SkipQueueHeadBody,
    SkipQueueHeadView,
)
from request_engine.modules.queue.application.commands.operator_select import OperatorSelectCommand
from request_engine.modules.queue.application.commands.recall_hold import RecallHoldCommand
from request_engine.modules.queue.application.commands.release_recall_hold import (
    ReleaseRecallHoldCommand,
)
from request_engine.modules.queue.application.commands.skip_queue_head import SkipQueueHeadCommand
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, require_capability

IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=1, max_length=250),
]


def create_same_day_selection_router(
    commands: PostgresSameDaySelectionCommands,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["live-queues"])

    async def actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def operator_select(
        queue_id: UUID,
        queue_entry_id: UUID,
        body: OperatorSelectBody,
        current: Annotated[ActorContext, Depends(actor)],
        idempotency_key: IdempotencyKey,
    ) -> QueueEntryView:
        require_capability(current, "queue.operator_select")
        entry = await commands.operator_select(
            OperatorSelectCommand(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                queue_id=queue_id,
                queue_entry_id=queue_entry_id,
                expected_revision=body.expected_revision,
                reason=body.reason,
                idempotency_key=idempotency_key,
            )
        )
        return QueueEntryView.from_contract(entry)

    async def recall_hold(
        queue_id: UUID,
        queue_entry_id: UUID,
        body: RecallHoldBody,
        current: Annotated[ActorContext, Depends(actor)],
        idempotency_key: IdempotencyKey,
    ) -> RecallHoldView:
        require_capability(current, "queue.recall_hold")
        hold = await commands.recall_hold(
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
        hold = await commands.release_recall_hold(
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

    async def skip_head(
        queue_id: UUID,
        body: SkipQueueHeadBody,
        current: Annotated[ActorContext, Depends(actor)],
        idempotency_key: IdempotencyKey,
    ) -> SkipQueueHeadView | None:
        require_capability(current, "queue.skip")
        result = await commands.skip_queue_head(
            SkipQueueHeadCommand(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                queue_id=queue_id,
                reason=body.reason,
                idempotency_key=idempotency_key,
            )
        )
        return SkipQueueHeadView.from_contract(result) if result is not None else None

    _add_routes(router, operator_select, recall_hold, release_hold, skip_head)
    return router


def _add_routes(router: APIRouter, operator_select, recall_hold, release_hold, skip_head) -> None:
    add_capability_route(
        router,
        "/queues/{queue_id}/entries/{queue_entry_id}/operator-select",
        operator_select,
        capability="queue.operator_select",
        methods=["POST"],
        response_model=QueueEntryView,
    )
    add_capability_route(
        router,
        "/queues/{queue_id}/entries/{queue_entry_id}/recall-hold",
        recall_hold,
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
    add_capability_route(
        router,
        "/queues/{queue_id}/skip",
        skip_head,
        capability="queue.skip",
        methods=["POST"],
        response_model=SkipQueueHeadView | None,
    )
