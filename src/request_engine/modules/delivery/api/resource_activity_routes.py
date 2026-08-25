from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, status

from request_engine.modules.delivery.adapters.db.live_service_operations import PostgresLiveServiceOperations
from request_engine.modules.delivery.api.live_models import (
    EndResourceActivityBody,
    ResourceActivityView,
    StartResourceActivityBody,
)
from request_engine.modules.delivery.application.resource_activity_commands import (
    EndResourceActivityCommand,
    StartResourceActivityCommand,
)
from request_engine.modules.delivery.contracts.service_session import ResourceActivityKind
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, require_capability

IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=250)]


def create_resource_activity_router(
    operations: PostgresLiveServiceOperations, actor_resolver: ActorResolver
) -> APIRouter:
    router = APIRouter()

    async def actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def start_activity(
        body: StartResourceActivityBody,
        current: Annotated[ActorContext, Depends(actor)],
        idempotency_key: IdempotencyKey,
    ) -> ResourceActivityView:
        require_capability(current, "resource_activity.start")
        result = await operations.start_resource_activity(
            StartResourceActivityCommand(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                resource_id=body.resource_id,
                location_id=body.location_id,
                kind=ResourceActivityKind(body.kind),
                idempotency_key=idempotency_key,
            )
        )
        return ResourceActivityView.from_contract(result)

    async def end_activity(
        resource_activity_id: UUID,
        body: EndResourceActivityBody,
        current: Annotated[ActorContext, Depends(actor)],
        idempotency_key: IdempotencyKey,
    ) -> ResourceActivityView:
        require_capability(current, "resource_activity.end")
        result = await operations.end_resource_activity(
            EndResourceActivityCommand(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                resource_activity_id=resource_activity_id,
                expected_revision=body.expected_revision,
                idempotency_key=idempotency_key,
            )
        )
        return ResourceActivityView.from_contract(result)

    add_capability_route(
        router,
        "/resource-activities",
        start_activity,
        capability="resource_activity.start",
        methods=["POST"],
        response_model=ResourceActivityView,
        status_code=status.HTTP_201_CREATED,
    )
    add_capability_route(
        router,
        "/resource-activities/{resource_activity_id}/end",
        end_activity,
        capability="resource_activity.end",
        methods=["POST"],
        response_model=ResourceActivityView,
    )
    return router
