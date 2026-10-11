from dataclasses import asdict
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel

from request_engine.modules.queue.application.queries.read_queue_configuration import (
    ServiceQueueConfigurationReader,
)
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, require_capability


class ServiceQueueConfigurationView(BaseModel):
    queue_id: UUID
    queue_key: str
    display_name: str
    location_id: UUID | None
    offering_id: UUID | None
    policy_key: str
    active: bool
    revision: int


class ServiceQueueConfigurationPageView(BaseModel):
    items: tuple[ServiceQueueConfigurationView, ...]
    next_cursor: UUID | None


def create_configuration_router(
    reader: ServiceQueueConfigurationReader, actor_resolver: ActorResolver
) -> APIRouter:
    router = APIRouter(prefix="/v1/queues/configuration", tags=["queue-configuration"])

    async def actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def configuration_list(
        request: Request,
        response: Response,
        authority_party_id: UUID,
        current: Annotated[ActorContext, Depends(actor)],
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        cursor: UUID | None = None,
    ) -> ServiceQueueConfigurationPageView:
        """Read current configuration, including inactive queues, with a live UUID cursor."""
        require_capability(current, "queue.read_configuration")
        response.headers["Cache-Control"] = "no-store"
        if set(request.query_params) - {"authority_party_id", "limit", "cursor"}:
            raise HTTPException(422, "Unsupported queue configuration filter")
        rows = await reader.read_queue_configuration(
            current.organization_id,
            principal_id=current.principal_id,
            authority_party_id=authority_party_id,
            after_id=cursor,
            limit=limit + 1,
        )
        page = rows[:limit]
        return ServiceQueueConfigurationPageView(
            items=tuple(ServiceQueueConfigurationView.model_validate(asdict(row)) for row in page),
            next_cursor=page[-1].queue_id if len(rows) > limit else None,
        )

    async def configuration_detail(
        queue_id: UUID,
        request: Request,
        response: Response,
        authority_party_id: UUID,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> ServiceQueueConfigurationView:
        """Read exact queue identity and revision. Missing and foreign IDs both return 404."""
        require_capability(current, "queue.read_configuration")
        response.headers["Cache-Control"] = "no-store"
        if set(request.query_params) - {"authority_party_id"}:
            raise HTTPException(422, "Unsupported queue configuration filter")
        rows = await reader.read_queue_configuration(
            current.organization_id,
            principal_id=current.principal_id,
            authority_party_id=authority_party_id,
            queue_id=queue_id,
            limit=1,
        )
        if not rows:
            raise HTTPException(404, "ServiceQueue not found")
        return ServiceQueueConfigurationView.model_validate(asdict(rows[0]))

    add_capability_route(
        router,
        "",
        configuration_list,
        capability="queue.read_configuration",
        methods=["GET"],
        operation_id="queue_service_queue_configuration_list",
        response_model=ServiceQueueConfigurationPageView,
    )
    add_capability_route(
        router,
        "/{queue_id}",
        configuration_detail,
        capability="queue.read_configuration",
        methods=["GET"],
        operation_id="queue_service_queue_configuration_read",
        response_model=ServiceQueueConfigurationView,
    )
    return router
