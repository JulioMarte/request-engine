from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, status

from request_engine.modules.operational_recovery.api.models import (
    CreateRecoveryProposalBody,
    ExecuteRecoveryBody,
    RecoveryExecutionView,
    RecoveryProposalView,
)
from request_engine.modules.operational_recovery.application.service import (
    CreateRecoveryProposalCommand,
    ExecuteRecoveryCommand,
    OperationalRecoveryService,
)
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, require_capability

IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=1, max_length=250),
]
_SUBJECT_OVERRIDE_PERMISSION = "appointments.subject_override"


def create_router(
    service: OperationalRecoveryService,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter(prefix="/v1/operational-recovery", tags=["operational-recovery"])

    async def authenticated_actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def create_proposal(
        service_queue_id: UUID,
        body: CreateRecoveryProposalBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
    ) -> RecoveryProposalView:
        require_capability(actor, "operational_recovery.propose")
        proposal = await service.create_proposal(
            CreateRecoveryProposalCommand(
                organization_id=actor.organization_id,
                principal_id=actor.principal_id,
                service_queue_id=service_queue_id,
                idempotency_key=idempotency_key,
                search_days=body.search_days,
            )
        )
        return RecoveryProposalView.from_contract(proposal)

    async def get_proposal(
        proposal_id: UUID,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
    ) -> RecoveryProposalView:
        require_capability(actor, "operational_recovery.read")
        proposal = await service.get_proposal(
            organization_id=actor.organization_id,
            proposal_id=proposal_id,
        )
        return RecoveryProposalView.from_contract(proposal)

    async def execute(
        proposal_id: UUID,
        body: ExecuteRecoveryBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
    ) -> RecoveryExecutionView:
        require_capability(actor, "operational_recovery.execute")
        execution = await service.execute(
            ExecuteRecoveryCommand(
                organization_id=actor.organization_id,
                principal_id=actor.principal_id,
                proposal_id=proposal_id,
                reservation_id=body.reservation_id,
                expected_source_fingerprint=body.expected_source_fingerprint,
                expected_proposal_fingerprint=body.expected_proposal_fingerprint,
                idempotency_key=idempotency_key,
                allow_subject_override=actor.allows(_SUBJECT_OVERRIDE_PERMISSION),
                notify=body.notify,
            )
        )
        return RecoveryExecutionView.from_contract(execution)

    add_capability_route(
        router,
        "/service-queues/{service_queue_id}/proposals",
        create_proposal,
        capability="operational_recovery.propose",
        methods=["POST"],
        response_model=RecoveryProposalView,
        status_code=status.HTTP_201_CREATED,
    )
    add_capability_route(
        router,
        "/proposals/{proposal_id}",
        get_proposal,
        capability="operational_recovery.read",
        methods=["GET"],
        response_model=RecoveryProposalView,
    )
    add_capability_route(
        router,
        "/proposals/{proposal_id}/execute",
        execute,
        capability="operational_recovery.execute",
        methods=["POST"],
        response_model=RecoveryExecutionView,
    )
    return router
