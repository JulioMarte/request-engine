"""Owner-authorized list of saved Location hours exceptions (ids for removal)."""

from dataclasses import asdict
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from request_engine.modules.catalog.application.queries.location_hours_exceptions import (
    LocationHoursExceptionQuery,
    LocationHoursExceptionReader,
)
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, require_capability


class LocationHoursExceptionParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    authority_party_id: UUID = Field(description="Party currently represented; not a grant")
    include_inactive: bool = False
    limit: int = Field(default=50, ge=1, le=100)
    after: UUID | None = None


class LocationHoursExceptionItemView(BaseModel):
    exception_id: UUID
    location_id: UUID
    start_at: datetime
    end_at: datetime
    exception_kind: Literal["available", "unavailable"]
    reason: str | None
    active: bool
    created_at: datetime
    updated_at: datetime


class LocationHoursExceptionPageView(BaseModel):
    items: tuple[LocationHoursExceptionItemView, ...]
    next_cursor: UUID | None
    operational_revision: int


def create_location_exception_router(
    reader: LocationHoursExceptionReader, actor_resolver: ActorResolver
) -> APIRouter:
    router = APIRouter(prefix="/v1/catalog", tags=["catalog"])

    async def actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def exceptions(
        location_id: UUID,
        params: Annotated[LocationHoursExceptionParams, Query()],
        response: Response,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> LocationHoursExceptionPageView:
        """List a Location's saved hours exceptions (holidays included) with ids.

        Active rows only unless include_inactive=true; ordered by id. Use the
        exception_id with catalog_location_hours_exception_deactivate and
        operational_revision as its expected_operational_revision. Requires
        operations.manage_profile authority; absent and foreign Locations are 404.
        """
        require_capability(current, "catalog.read_configuration")
        page = await reader.location_hours_exceptions(
            LocationHoursExceptionQuery(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                location_id=location_id,
                **params.model_dump(),
            )
        )
        if page is None:
            raise HTTPException(404, detail="Location not found")
        response.headers["Cache-Control"] = "no-store"
        items = page.items[: params.limit]
        return LocationHoursExceptionPageView(
            items=tuple(LocationHoursExceptionItemView(**asdict(item)) for item in items),
            next_cursor=items[-1].exception_id if len(page.items) > params.limit else None,
            operational_revision=page.operational_revision,
        )

    add_capability_route(
        router,
        "/locations/{location_id}/hours-exceptions",
        exceptions,
        capability="catalog.read_configuration",
        methods=["GET"],
        operation_id="catalog_location_hours_exception_list",
        response_model=LocationHoursExceptionPageView,
    )
    return router
