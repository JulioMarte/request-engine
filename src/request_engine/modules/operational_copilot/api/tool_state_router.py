from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from request_engine.modules.operational_copilot.api.tool_state_models import (
    AtRiskAssessmentView,
    QueueIntakeView,
    RecoveryIncidentView,
)
from request_engine.modules.operational_copilot.application.ports import AtRiskReservationReader
from request_engine.modules.operational_copilot.contracts import AtRiskReservationsQuery
from request_engine.modules.operational_recovery.contracts.copilot import (
    CopilotRecoveryIncidentReader,
)
from request_engine.modules.queue.contracts.intake import QueueIntakeControlPort
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, require_capability


def create_tool_state_router(
    *,
    actor_resolver: ActorResolver,
    at_risk_reader: AtRiskReservationReader,
    intake_reader: QueueIntakeControlPort,
    incident_reader: CopilotRecoveryIncidentReader,
) -> APIRouter:
    router = APIRouter(prefix="/v1/operational-copilot/tools", tags=["operational-copilot-tools"])

    async def actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def intake(
        service_queue_id: UUID,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> QueueIntakeView:
        require_capability(current, "operational_copilot.interpret")
        state = await intake_reader.get_intake_control(current.organization_id, service_queue_id)
        return QueueIntakeView.from_state(state)

    async def incident(
        service_queue_id: UUID,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> RecoveryIncidentView:
        require_capability(current, "operational_copilot.interpret")
        value = await incident_reader.get_open_incident_for_queue(
            organization_id=current.organization_id,
            service_queue_id=service_queue_id,
        )
        if value is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="no open recovery incident")
        return RecoveryIncidentView.from_incident(value)

    async def at_risk(
        service_queue_id: UUID,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> AtRiskAssessmentView:
        require_capability(current, "operational_copilot.interpret")
        assessment = await at_risk_reader.read(
            AtRiskReservationsQuery(current.organization_id, service_queue_id)
        )
        return AtRiskAssessmentView.from_assessment(assessment)

    add_capability_route(
        router,
        "/queues/{service_queue_id}/intake",
        intake,
        capability="operational_copilot.interpret",
        methods=["GET"],
        operation_id="copilot_queue_intake_state",
        response_model=QueueIntakeView,
    )
    add_capability_route(
        router,
        "/queues/{service_queue_id}/recovery-incident",
        incident,
        capability="operational_copilot.interpret",
        methods=["GET"],
        operation_id="copilot_open_recovery_incident",
        response_model=RecoveryIncidentView,
    )
    add_capability_route(
        router,
        "/queues/{service_queue_id}/at-risk-reservations",
        at_risk,
        capability="operational_copilot.interpret",
        methods=["GET"],
        operation_id="copilot_at_risk_reservations",
        response_model=AtRiskAssessmentView,
    )
    return router
