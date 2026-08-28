from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, status

from request_engine.modules.operational_recovery.api.workflow_models import (
    ExtendRecoveryDayBody,
    RecoveryActionView,
    SetRecoveryIntakeBody,
)
from request_engine.modules.operational_recovery.application.workflow_commands import (
    ExtendRecoveryDayCommand,
    SetRecoveryIntakeCommand,
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


def create_workflow_router(
    service: RecoveryWorkflowService,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter(prefix="/v1/operational-recovery", tags=["operational-recovery"])

    async def authenticated_actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def set_intake(
        incident_id: UUID,
        body: SetRecoveryIntakeBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
    ) -> RecoveryActionView:
        require_capability(actor, "operational_recovery.execute")
        action = await service.set_intake(
            SetRecoveryIntakeCommand(
                organization_id=actor.organization_id,
                principal_id=actor.principal_id,
                incident_id=incident_id,
                expected_source_revision=body.expected_source_revision,
                accepting=body.accepting,
                idempotency_key=idempotency_key,
                reason=body.reason,
                effective_until=body.effective_until,
            )
        )
        return RecoveryActionView.from_contract(action)

    async def extend_day(
        incident_id: UUID,
        body: ExtendRecoveryDayBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
    ) -> RecoveryActionView:
        require_capability(actor, "operational_recovery.execute")
        action = await service.extend_day(
            ExtendRecoveryDayCommand(
                organization_id=actor.organization_id,
                principal_id=actor.principal_id,
                authority_party_id=body.authority_party_id,
                incident_id=incident_id,
                expected_source_revision=body.expected_source_revision,
                assignment_id=body.assignment_id,
                start_at=body.start_at,
                end_at=body.end_at,
                expected_location_operational_revision=(
                    body.expected_location_operational_revision
                ),
                expected_resource_availability_revision=(
                    body.expected_resource_availability_revision
                ),
                idempotency_key=idempotency_key,
                reason=body.reason,
            )
        )
        return RecoveryActionView.from_contract(action)

    add_capability_route(
        router,
        "/incidents/{incident_id}/intake-control",
        set_intake,
        capability="operational_recovery.execute",
        methods=["POST"],
        response_model=RecoveryActionView,
        status_code=status.HTTP_200_OK,
    )
    add_capability_route(
        router,
        "/incidents/{incident_id}/extend-day",
        extend_day,
        capability="operational_recovery.execute",
        methods=["POST"],
        response_model=RecoveryActionView,
        status_code=status.HTTP_200_OK,
    )
    return router
