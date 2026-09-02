from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request

from request_engine.modules.queue.adapters.db.same_day_selection_commands import (
    PostgresSameDaySelectionCommands,
)
from request_engine.modules.queue.api.models import QueueEntryView
from request_engine.modules.queue.api.same_day_selection_models import (
    OperatorSelectBody,
    SkipQueueHeadBody,
    SkipQueueHeadView,
)
from request_engine.modules.queue.application.commands.operator_select import OperatorSelectCommand
from request_engine.modules.queue.application.commands.skip_queue_head import SkipQueueHeadCommand
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, require_capability

IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=1, max_length=250),
]


def create_same_day_dispatch_router(
    commands: PostgresSameDaySelectionCommands,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter()

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
        "/queues/{queue_id}/skip",
        skip_head,
        capability="queue.skip",
        methods=["POST"],
        response_model=SkipQueueHeadView | None,
    )
    return router
