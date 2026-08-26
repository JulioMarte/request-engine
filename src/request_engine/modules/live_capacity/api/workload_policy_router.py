from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, status

from request_engine.modules.live_capacity.adapters.db.workload_policy_commands import (
    create_workload_estimate_policy,
    update_workload_estimate_policy,
)
from request_engine.modules.live_capacity.api.models import (
    CreateWorkloadEstimatePolicyBody,
    UpdateWorkloadEstimatePolicyBody,
    WorkloadEstimatePolicyView,
)
from request_engine.modules.live_capacity.application.commands.policy import (
    CreateWorkloadEstimatePolicyCommand,
    UpdateWorkloadEstimatePolicyCommand,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, require_capability

IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=1, max_length=250),
]


def create_workload_policy_router(
    session_factory: SessionFactory,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter()

    async def actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def create_policy(
        body: CreateWorkloadEstimatePolicyBody,
        current: Annotated[ActorContext, Depends(actor)],
        idempotency_key: IdempotencyKey,
    ) -> WorkloadEstimatePolicyView:
        require_capability(current, "live_capacity.configure_estimate")
        policy = await create_workload_estimate_policy(
            session_factory,
            CreateWorkloadEstimatePolicyCommand(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                workload_classification_id=body.workload_classification_id,
                duration_seconds=body.duration_seconds,
                idempotency_key=idempotency_key,
            ),
        )
        return WorkloadEstimatePolicyView.from_contract(policy)

    async def update_policy(
        policy_id: UUID,
        body: UpdateWorkloadEstimatePolicyBody,
        current: Annotated[ActorContext, Depends(actor)],
        idempotency_key: IdempotencyKey,
    ) -> WorkloadEstimatePolicyView:
        require_capability(current, "live_capacity.configure_estimate")
        policy = await update_workload_estimate_policy(
            session_factory,
            UpdateWorkloadEstimatePolicyCommand(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                policy_id=policy_id,
                duration_seconds=body.duration_seconds,
                active=body.active,
                expected_revision=body.expected_revision,
                idempotency_key=idempotency_key,
            ),
        )
        return WorkloadEstimatePolicyView.from_contract(policy)

    add_capability_route(
        router,
        "/live-capacity/workload-estimate-policies",
        create_policy,
        capability="live_capacity.configure_estimate",
        methods=["POST"],
        response_model=WorkloadEstimatePolicyView,
        status_code=status.HTTP_201_CREATED,
    )
    add_capability_route(
        router,
        "/live-capacity/workload-estimate-policies/{policy_id}",
        update_policy,
        capability="live_capacity.configure_estimate",
        methods=["POST"],
        response_model=WorkloadEstimatePolicyView,
    )
    return router
