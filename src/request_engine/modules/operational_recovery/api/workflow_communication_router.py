from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, status

from request_engine.modules.operational_recovery.api.workflow_models import (
    CommunicateImpactBody,
    RecoveryActionView,
)
from request_engine.modules.operational_recovery.application.workflow_commands import (
    CommunicateImpactRecoveryActionCommand,
)
from request_engine.modules.operational_recovery.application.workflow_service import (
    RecoveryWorkflowService,
)
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, require_capability

IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=1, max_length=250),
]


def create_communication_router(
    service: RecoveryWorkflowService,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter(prefix="/v1/operational-recovery", tags=["operational-recovery"])

    async def authenticated_actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def communicate_impact(
        incident_id: UUID,
        body: CommunicateImpactBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
    ) -> RecoveryActionView:
        require_capability(actor, "operational_recovery.execute")
        action = await service.communicate_impact(
            CommunicateImpactRecoveryActionCommand(
                organization_id=actor.organization_id,
                principal_id=actor.principal_id,
                incident_id=incident_id,
                expected_source_revision=body.expected_source_revision,
                recipient_party_id=body.recipient_party_id,
                idempotency_key=idempotency_key,
                message=body.message,
                not_before=body.not_before,
            )
        )
        return RecoveryActionView.from_contract(action)

    add_capability_route(
        router,
        "/incidents/{incident_id}/communicate-impact",
        communicate_impact,
        capability="operational_recovery.execute",
        methods=["POST"],
        operation_id="operational_recovery_communicate_impact",
        response_model=RecoveryActionView,
        status_code=status.HTTP_200_OK,
    )
    return router
