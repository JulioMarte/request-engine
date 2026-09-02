from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from request_engine.modules.queue.adapters.db.triage_commands import PostgresQueueTriageCommands
from request_engine.modules.queue.api.triage_http_support import IdempotencyKey
from request_engine.modules.queue.api.triage_models import QueueTriageResultView, SkipBody
from request_engine.modules.queue.application.commands.triage import SkipCommand
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, require_capability


def create_skip_router(
    commands: PostgresQueueTriageCommands,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter()

    async def actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def skip(
        queue_entry_id: UUID,
        body: SkipBody,
        current: Annotated[ActorContext, Depends(actor)],
        idempotency_key: IdempotencyKey,
    ) -> QueueTriageResultView:
        require_capability(current, "queue.skip")
        result = await commands.skip(
            SkipCommand(
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
        "/queue-entries/{queue_entry_id}/skip",
        skip,
        capability="queue.skip",
        methods=["POST"],
        response_model=QueueTriageResultView,
    )
    return router
