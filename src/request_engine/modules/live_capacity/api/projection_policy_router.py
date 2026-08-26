from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, status

from request_engine.modules.live_capacity.adapters.db.projection_policy_commands import (
    create_projection_scope,
    update_projection_scope,
)
from request_engine.modules.live_capacity.api.models import (
    CreateProjectionScopeBody,
    ProjectionScopePolicyView,
    UpdateProjectionScopeBody,
)
from request_engine.modules.live_capacity.application.commands.policy import (
    CreateProjectionScopeCommand,
    UpdateProjectionScopeCommand,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, require_capability

IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=1, max_length=250),
]


def create_projection_policy_router(
    session_factory: SessionFactory,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter()

    async def actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def create_policy(
        body: CreateProjectionScopeBody,
        current: Annotated[ActorContext, Depends(actor)],
        idempotency_key: IdempotencyKey,
    ) -> ProjectionScopePolicyView:
        require_capability(current, "live_capacity.configure_scope")
        policy = await create_projection_scope(
            session_factory,
            CreateProjectionScopeCommand(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                service_queue_id=body.service_queue_id,
                resource_id=body.resource_id,
                location_id=body.location_id,
                idempotency_key=idempotency_key,
            ),
        )
        return ProjectionScopePolicyView.from_contract(policy)

    async def update_policy(
        policy_id: UUID,
        body: UpdateProjectionScopeBody,
        current: Annotated[ActorContext, Depends(actor)],
        idempotency_key: IdempotencyKey,
    ) -> ProjectionScopePolicyView:
        require_capability(current, "live_capacity.configure_scope")
        policy = await update_projection_scope(
            session_factory,
            UpdateProjectionScopeCommand(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                policy_id=policy_id,
                resource_id=body.resource_id,
                location_id=body.location_id,
                active=body.active,
                expected_revision=body.expected_revision,
                idempotency_key=idempotency_key,
            ),
        )
        return ProjectionScopePolicyView.from_contract(policy)

    add_capability_route(
        router,
        "/v1/live-capacity/projection-policies",
        create_policy,
        capability="live_capacity.configure_scope",
        methods=["POST"],
        response_model=ProjectionScopePolicyView,
        status_code=status.HTTP_201_CREATED,
    )
    add_capability_route(
        router,
        "/v1/live-capacity/projection-policies/{policy_id}",
        update_policy,
        capability="live_capacity.configure_scope",
        methods=["POST"],
        operation_id="live_capacity_configure_scope_update",
        response_model=ProjectionScopePolicyView,
    )
    return router
