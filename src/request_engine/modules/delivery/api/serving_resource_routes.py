from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from request_engine.modules.delivery.application.serving_resource_query import (
    ServingResourceReader,
)
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, require_capability


class ServingResourceView(BaseModel):
    resource_id: UUID
    display_name: str


class LocationServingResourcesView(BaseModel):
    location_id: UUID
    observed_at: datetime
    items: tuple[ServingResourceView, ...]


def create_serving_resource_router(
    reader: ServingResourceReader,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter()

    async def actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def serving_resources(
        location_id: UUID,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> LocationServingResourcesView:
        """Resources that can start service at this Location right now.

        Active Resources with an active assignment in force at the Location at
        ``observed_at`` — the same preconditions ``service_session_start``
        re-checks. Requires ``service_session.start``; no Party representation,
        because it only names who works here, never supply configuration.
        """

        require_capability(current, "service_session.start")
        found = await reader.read_serving_resources(current.organization_id, location_id)
        if found is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="location not found")
        return LocationServingResourcesView(
            location_id=found.location_id,
            observed_at=found.observed_at,
            items=tuple(
                ServingResourceView(resource_id=item.resource_id, display_name=item.display_name)
                for item in found.resources
            ),
        )

    add_capability_route(
        router,
        "/locations/{location_id}/serving-resources",
        serving_resources,
        capability="service_session.start",
        methods=["GET"],
        operation_id="front_desk_serving_resources",
        response_model=LocationServingResourcesView,
    )
    return router
