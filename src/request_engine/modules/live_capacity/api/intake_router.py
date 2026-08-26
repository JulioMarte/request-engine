from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from request_engine.modules.live_capacity.adapters.db.intake_reader import (
    PostgresIntakeEvaluationReader,
)
from request_engine.modules.live_capacity.api.intake_models import IntakeEvaluationView
from request_engine.modules.live_capacity.application.queries.intake import EvaluateIntakeQuery
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, require_capability


def create_intake_router(
    reader: PostgresIntakeEvaluationReader,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter()

    async def actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def evaluate(
        service_queue_id: UUID,
        workload_classification_id: UUID,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> IntakeEvaluationView:
        require_capability(current, "live_capacity.evaluate_intake")
        result = await reader.evaluate(
            EvaluateIntakeQuery(
                organization_id=current.organization_id,
                service_queue_id=service_queue_id,
                workload_classification_id=workload_classification_id,
            )
        )
        return IntakeEvaluationView.from_contract(result)

    add_capability_route(
        router,
        "/v1/live-capacity/queues/{service_queue_id}/evaluate-intake",
        evaluate,
        capability="live_capacity.evaluate_intake",
        methods=["GET"],
        response_model=IntakeEvaluationView,
    )
    return router
