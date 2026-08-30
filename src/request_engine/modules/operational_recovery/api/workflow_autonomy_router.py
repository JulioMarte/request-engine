from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request

from request_engine.modules.operational_recovery.api.workflow_models import (
    RecoveryAutonomyPolicyBody,
    RecoveryAutonomyPolicyView,
)
from request_engine.modules.operational_recovery.application.recovery_autonomy_policy import (
    ConfigureRecoveryAutonomyCommand,
    RecoveryAutonomyConfiguration,
)
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, require_capability

IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=1, max_length=250),
]


def create_autonomy_router(
    autonomy: RecoveryAutonomyConfiguration,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter(prefix="/v1/operational-recovery", tags=["operational-recovery"])

    async def authenticated_actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def configure_autonomy(
        service_queue_id: UUID,
        body: RecoveryAutonomyPolicyBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
    ) -> RecoveryAutonomyPolicyView:
        require_capability(actor, "operational_recovery.configure_autonomy")
        policy = await autonomy.configure(
            ConfigureRecoveryAutonomyCommand(
                organization_id=actor.organization_id,
                principal_id=actor.principal_id,
                service_queue_id=service_queue_id,
                enabled=body.enabled,
                max_delay_minutes=body.max_delay_minutes,
                max_auto_actions_per_incident=body.max_auto_actions_per_incident,
                idempotency_key=idempotency_key,
            )
        )
        return RecoveryAutonomyPolicyView.from_policy(policy)

    add_capability_route(
        router,
        "/queues/{service_queue_id}/autonomy-policy",
        configure_autonomy,
        capability="operational_recovery.configure_autonomy",
        methods=["POST"],
        operation_id="operational_recovery_configure_autonomy",
        response_model=RecoveryAutonomyPolicyView,
    )
    return router
