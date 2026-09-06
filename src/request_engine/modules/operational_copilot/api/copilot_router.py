from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from request_engine.modules.operational_copilot.api.models import (
    CopilotAtRiskCommitmentView,
    CopilotAtRiskView,
    CopilotExecutionView,
    CopilotInterpretationView,
    CopilotInterpretBody,
    interpretation_view,
)
from request_engine.modules.operational_copilot.application.copilot import OperationalCopilot
from request_engine.modules.operational_copilot.contracts import (
    AtRiskReservationsQuery,
    CopilotContext,
)
from request_engine.modules.operational_copilot.errors import (
    CopilotConflict,
    CopilotPolicyRejected,
    CopilotSemanticError,
)
from request_engine.modules.operational_copilot.lowering.operations import CopilotOperation
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, require_capability

IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=1, max_length=250),
]


def create_copilot_router(
    *,
    copilot: OperationalCopilot,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter(prefix="/v1/operational-copilot", tags=["operational-copilot"])

    async def authenticated_actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def interpret(
        body: CopilotInterpretBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
    ) -> CopilotInterpretationView | CopilotAtRiskView:
        require_capability(actor, "operational_copilot.interpret")
        context = _context(actor, idempotency_key)
        operation = await _refusals(copilot, context, body.text)
        if isinstance(operation, AtRiskReservationsQuery):
            assessment = await copilot.read_at_risk(context, operation)
            return CopilotAtRiskView(
                action="show_at_risk_reservations",
                service_queue_id=assessment.service_queue_id,
                projection_state=str(assessment.projection_state.value),
                shortfall_seconds=assessment.shortfall_seconds,
                source_fingerprint=assessment.source_fingerprint,
                at_risk_reservations=[
                    CopilotAtRiskCommitmentView(
                        reservation_id=fact.reservation_id,
                        reservation_revision=fact.reservation_revision,
                        planned_starts_at=fact.planned_starts_at,
                        planned_ends_at=fact.planned_ends_at,
                    )
                    for fact in assessment.affected_commitments
                ],
            )
        return interpretation_view(operation)

    async def execute(
        body: CopilotInterpretBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
    ) -> CopilotExecutionView:
        require_capability(actor, "operational_copilot.execute")
        context = _context(actor, idempotency_key)
        operation = await _refusals(copilot, context, body.text)
        try:
            owner_capability = copilot.execution_capability(operation)
            if owner_capability is not None:
                require_capability(actor, owner_capability)
            receipt = await copilot.execute(operation)
        except CopilotConflict as error:
            raise HTTPException(status.HTTP_409_CONFLICT, detail=str(error)) from error
        except CopilotSemanticError as error:
            raise _unprocessable(error) from error
        return CopilotExecutionView.from_receipt(receipt)

    add_capability_route(
        router,
        "/interpret",
        interpret,
        capability="operational_copilot.interpret",
        methods=["POST"],
        response_model=CopilotInterpretationView | CopilotAtRiskView,
    )
    add_capability_route(
        router,
        "/execute",
        execute,
        capability="operational_copilot.execute",
        methods=["POST"],
        response_model=CopilotExecutionView,
    )
    return router


def _context(actor: ActorContext, idempotency_key: str) -> CopilotContext:
    return CopilotContext(actor.organization_id, actor.principal_id, idempotency_key)


def _unprocessable(error: Exception) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error))


async def _refusals(
    copilot: OperationalCopilot,
    context: CopilotContext,
    text: str,
) -> CopilotOperation:
    try:
        return await copilot.interpret(context, text)
    except CopilotPolicyRejected as error:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    except CopilotSemanticError as error:
        raise _unprocessable(error) from error
