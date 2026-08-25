from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request

from request_engine.modules.queue.adapters.db.live_queue_commands import (
    PostgresLiveQueueCommands,
)
from request_engine.modules.queue.api.live_models import (
    ClassifyExpectedWorkloadBody,
    LiveQueueEntryView,
)
from request_engine.modules.queue.application.live_commands import (
    ClassifyExpectedWorkloadCommand,
)
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, require_capability

IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=1, max_length=250),
]


def create_live_classification_router(
    commands: PostgresLiveQueueCommands,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter()

    async def actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def classify_expected_workload(
        queue_entry_id: UUID,
        body: ClassifyExpectedWorkloadBody,
        current: Annotated[ActorContext, Depends(actor)],
        idempotency_key: IdempotencyKey,
    ) -> LiveQueueEntryView:
        require_capability(current, "queue.classify_expected_workload")
        item = await commands.classify_expected_workload(
            ClassifyExpectedWorkloadCommand(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                queue_entry_id=queue_entry_id,
                expected_revision=body.expected_revision,
                expected_workload_classification_id=(body.expected_workload_classification_id),
                idempotency_key=idempotency_key,
            )
        )
        return LiveQueueEntryView.from_contract(item)

    add_capability_route(
        router,
        "/queue-entries/{queue_entry_id}/expected-workload",
        classify_expected_workload,
        capability="queue.classify_expected_workload",
        methods=["POST"],
        response_model=LiveQueueEntryView,
    )
    return router
