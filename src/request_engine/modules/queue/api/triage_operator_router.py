from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from request_engine.modules.queue.adapters.db.triage_commands import PostgresQueueTriageCommands
from request_engine.modules.queue.api.triage_http_support import IdempotencyKey
from request_engine.modules.queue.api.triage_models import (
    OperatorSelectBody,
    QueueTriageResultView,
)
from request_engine.modules.queue.application.commands.triage import OperatorSelectCommand
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, require_capability


def create_operator_select_router(
    commands: PostgresQueueTriageCommands,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter()

    async def actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def operator_select(
        queue_entry_id: UUID,
        body: OperatorSelectBody,
        current: Annotated[ActorContext, Depends(actor)],
        idempotency_key: IdempotencyKey,
    ) -> QueueTriageResultView:
        require_capability(current, "queue.operator_select")
        result = await commands.operator_select(
            OperatorSelectCommand(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                queue_entry_id=queue_entry_id,
                reason=body.reason,
                expected_revision=body.expected_revision,
                idempotency_key=idempotency_key,
            )
        )
        return QueueTriageResultView.from_contract(result)

    add_capability_route(
        router,
        "/queue-entries/{queue_entry_id}/operator-select",
        operator_select,
        capability="queue.operator_select",
        methods=["POST"],
        response_model=QueueTriageResultView,
    )
    return router
