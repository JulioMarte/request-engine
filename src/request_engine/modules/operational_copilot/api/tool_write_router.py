from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from request_engine.modules.operational_copilot.api.models import CopilotExecutionView
from request_engine.modules.operational_copilot.api.tool_write_models import (
    CreateRecoveryProposalBody,
    ExecuteRecoveryBody,
    ExtendRecoveryDayBody,
    PublishDiscoverySupplyBody,
    RevokeDiscoveryPublicationBody,
    SetRecoveryIntakeBody,
)
from request_engine.modules.operational_copilot.application.copilot import OperationalCopilot
from request_engine.modules.operational_copilot.contracts import CopilotContext, CopilotIntent
from request_engine.modules.operational_copilot.errors import (
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


def create_tool_write_router(
    *,
    copilot: OperationalCopilot,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter(prefix="/v1/operational-copilot/tools", tags=["operational-copilot-tools"])

    async def actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def proposal(
        body: CreateRecoveryProposalBody,
        current: Annotated[ActorContext, Depends(actor)],
        key: IdempotencyKey,
    ) -> CopilotExecutionView:
        return await _execute(copilot, current, key, body.to_intent())

    async def recovery_execution(
        body: ExecuteRecoveryBody,
        current: Annotated[ActorContext, Depends(actor)],
        key: IdempotencyKey,
    ) -> CopilotExecutionView:
        return await _execute(copilot, current, key, body.to_intent())

    async def intake(
        body: SetRecoveryIntakeBody,
        current: Annotated[ActorContext, Depends(actor)],
        key: IdempotencyKey,
    ) -> CopilotExecutionView:
        return await _execute(copilot, current, key, body.to_intent())

    async def day_extension(
        body: ExtendRecoveryDayBody,
        current: Annotated[ActorContext, Depends(actor)],
        key: IdempotencyKey,
    ) -> CopilotExecutionView:
        return await _execute(copilot, current, key, body.to_intent())

    async def publication(
        body: PublishDiscoverySupplyBody,
        current: Annotated[ActorContext, Depends(actor)],
        key: IdempotencyKey,
    ) -> CopilotExecutionView:
        return await _execute(copilot, current, key, body.to_intent())

    async def revocation(
        body: RevokeDiscoveryPublicationBody,
        current: Annotated[ActorContext, Depends(actor)],
        key: IdempotencyKey,
    ) -> CopilotExecutionView:
        return await _execute(copilot, current, key, body.to_intent())

    routes = (
        ("/recovery/proposals", proposal),
        ("/recovery/executions", recovery_execution),
        ("/recovery/intake", intake),
        ("/recovery/day-extensions", day_extension),
        ("/discovery/publications", publication),
        ("/discovery/revocations", revocation),
    )
    for path, endpoint in routes:
        add_capability_route(
            router,
            path,
            endpoint,
            capability="operational_copilot.execute",
            methods=["POST"],
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
    except CopilotSemanticError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
