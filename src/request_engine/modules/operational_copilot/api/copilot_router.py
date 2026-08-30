from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from request_engine.modules.operational_copilot.api.models import (
    CopilotAtRiskCommitmentView,
    CopilotAtRiskView,
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
    CopilotPolicyRejected,
    CopilotSemanticError,
)
from request_engine.modules.operational_copilot.lowering import CopilotOperation
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
        context = CopilotContext(
            organization_id=actor.organization_id,
            principal_id=actor.principal_id,
            idempotency_key=idempotency_key,
            authority_party_id=body.authority_party_id,
        )
        operation = await _refusals(copilot.interpret, context, body.text)
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
                        contextual_commitment=fact.contextual_commitment,
                    )
                    for fact in assessment.affected_commitments
                ],
            )
        return interpretation_view(operation)

    router.add_api_route("/interpret", interpret, methods=["POST"])
    return router


async def _refusals(
    operate: Callable[[CopilotContext, str], Awaitable[CopilotOperation]],
    context: CopilotContext,
    text: str,
) -> CopilotOperation:
    try:
        return await operate(context, text)
    except CopilotPolicyRejected as error:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    except CopilotSemanticError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
