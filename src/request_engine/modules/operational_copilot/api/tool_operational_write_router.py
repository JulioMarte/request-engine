from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from request_engine.modules.operational_copilot.api.models import CopilotExecutionView
from request_engine.modules.operational_copilot.api.tool_operational_write_models import (
    ExtendOperationalDayBody,
    SetOperationalIntakeBody,
)
from request_engine.modules.operational_copilot.application.copilot import OperationalCopilot
from request_engine.modules.operational_copilot.contracts import CopilotContext, CopilotIntent
from request_engine.modules.operational_copilot.errors import (
    CopilotConflict,
    CopilotPolicyRejected,
    CopilotSemanticError,
)
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, require_capability

IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=1, max_length=250),
]


def create_tool_operational_write_router(
    *,
    copilot: OperationalCopilot,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter(prefix="/v1/operational-copilot/tools", tags=["operational-copilot-tools"])

    async def actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def intake(
        body: SetOperationalIntakeBody,
        current: Annotated[ActorContext, Depends(actor)],
        key: IdempotencyKey,
    ) -> CopilotExecutionView:
        return await _execute(copilot, current, key, body.to_intent())

    async def day_extension(
        body: ExtendOperationalDayBody,
        current: Annotated[ActorContext, Depends(actor)],
        key: IdempotencyKey,
    ) -> CopilotExecutionView:
        return await _execute(copilot, current, key, body.to_intent())

    add_capability_route(
        router,
        "/queues/intake-control",
        intake,
        capability="operational_copilot.execute",
        methods=["POST"],
        operation_id="copilot_set_operational_intake",
        response_model=CopilotExecutionView,
    )
    add_capability_route(
        router,
        "/assignments/day-extensions",
        day_extension,
        capability="operational_copilot.execute",
        methods=["POST"],
        operation_id="copilot_extend_operational_day",
        response_model=CopilotExecutionView,
    )
    return router


async def _execute(
    copilot: OperationalCopilot,
    actor: ActorContext,
    idempotency_key: str,
    intent: CopilotIntent,
) -> CopilotExecutionView:
    require_capability(actor, "operational_copilot.execute")
    context = CopilotContext(actor.organization_id, actor.principal_id, idempotency_key)
    try:
        operation = await copilot.admit(context, intent)
        owner_capability = copilot.execution_capability(operation)
        if owner_capability is not None:
            require_capability(actor, owner_capability)
        return CopilotExecutionView.from_receipt(await copilot.execute(operation))
    except CopilotPolicyRejected as error:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    except CopilotConflict as error:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(error)) from error
    except CopilotSemanticError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
