from dataclasses import asdict
from datetime import date, datetime, time
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from request_engine.modules.booking.application.queries.supply_configuration import (
    SupplyConfigurationQuery,
    SupplyConfigurationReader,
)
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, require_capability


class SupplyConfigurationParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    authority_party_id: UUID = Field(
        description="Party the actor currently represents; never a grant of authority"
    )
    limit: int = Field(default=50, ge=1, le=100)
    after: UUID | None = Field(
        default=None, description="Pass next_cursor from the previous page with the same filters"
    )
    assignment_id: UUID | None = None


class ResourceConfigurationParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    authority_party_id: UUID = Field(
        description="Party the actor currently represents; never a grant of authority"
    )
    limit: int = Field(default=50, ge=1, le=100)
    after: UUID | None = Field(
        default=None, description="Pass next_cursor from the previous page with the same filters"
    )
    resource_id: UUID | None = None


class AssignmentConfigurationParams(ResourceConfigurationParams):
    location_id: UUID | None = None
    assignment_id: UUID | None = None


class ResourceConfigurationView(BaseModel):
    resource_id: UUID
    resource_key: str
    display_name: str
    capacity_model: str
    capacity_units: int
    active: bool
    availability_revision: int
    capability_ids: tuple[UUID, ...]


class AssignmentConfigurationView(BaseModel):
    assignment_id: UUID
    resource_id: UUID
    location_id: UUID
    status: str
    effective_from: datetime
    effective_until: datetime | None
    assignment_revision: int
    resource_availability_revision: int


class TermsConfigurationView(BaseModel):
    context_terms_id: UUID
    resource_location_assignment_id: UUID
    offering_version_id: UUID
    effective_from: datetime
    effective_until: datetime | None
    amount: Decimal | None
    currency: str | None
    planned_duration_minutes: int | None
    bookable: bool
    active: bool
    revision: int


class ResourceConfigurationPageView(BaseModel):
    items: tuple[ResourceConfigurationView, ...]
    next_cursor: UUID | None


class AssignmentConfigurationPageView(BaseModel):
    items: tuple[AssignmentConfigurationView, ...]
    next_cursor: UUID | None


class TermsConfigurationPageView(BaseModel):
    items: tuple[TermsConfigurationView, ...]
    next_cursor: UUID | None


class SupplyWindowParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    authority_party_id: UUID = Field(
        description="Party the actor currently represents; never a grant of authority"
    )
    limit: int = Field(default=50, ge=1, le=100)
    after: UUID | None = Field(
        default=None, description="Pass next_cursor from the previous page with the same filters"
    )


class AvailabilityConfigurationView(BaseModel):
    window_id: UUID
    assignment_id: UUID
    weekday: int
    local_start: time
    local_end: time
    valid_from: date | None
    valid_until: date | None
    active: bool
    resource_availability_revision: int


class AvailabilityConfigurationPageView(BaseModel):
    items: tuple[AvailabilityConfigurationView, ...]
    next_cursor: UUID | None


class ExceptionConfigurationView(BaseModel):
    exception_id: UUID
    resource_id: UUID
    assignment_id: UUID | None
    start_at: datetime
    end_at: datetime
    exception_kind: str
    reason: str | None
    active: bool
    resource_availability_revision: int


class ExceptionConfigurationPageView(BaseModel):
    items: tuple[ExceptionConfigurationView, ...]
    next_cursor: UUID | None


def create_supply_configuration_router(
    *, reader: SupplyConfigurationReader, actor_resolver: ActorResolver
) -> APIRouter:
    router = APIRouter(tags=["booking-configuration"])

    async def actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    def query(
        params: SupplyConfigurationParams | ResourceConfigurationParams,
        current: ActorContext,
    ) -> SupplyConfigurationQuery:
        require_capability(current, "booking.read_supply")
        return SupplyConfigurationQuery(
            organization_id=current.organization_id,
            principal_id=current.principal_id,
            **params.model_dump(),
        )

    async def resources(
        params: Annotated[ResourceConfigurationParams, Query()],
        response: Response,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> ResourceConfigurationPageView:
        """Read capacity and availability revisions before changing supply.

        Requires current operations.manage_supply Party authority. Filter by resource_id
        for a particular resource. Follow next_cursor as after, preserving filters;
        null means no further page was observed. This is a live read, not a snapshot.
        """
        rows = await reader.read_resources(query(params, current))
        response.headers["Cache-Control"] = "no-store"
        return ResourceConfigurationPageView(
            items=tuple(ResourceConfigurationView(**asdict(row)) for row in rows[: params.limit]),
            next_cursor=rows[params.limit - 1].resource_id if len(rows) > params.limit else None,
        )

    async def assignments(
        params: Annotated[AssignmentConfigurationParams, Query()],
        response: Response,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> AssignmentConfigurationPageView:
        """Read location assignments and their current revisions.

        Requires current operations.manage_supply Party authority. Keep assignment_revision
        and resource_availability_revision distinct when preparing subsequent commands.
        Follow next_cursor as after with unchanged filters.
        """
        rows = await reader.read_assignments(query(params, current))
        response.headers["Cache-Control"] = "no-store"
        return AssignmentConfigurationPageView(
            items=tuple(AssignmentConfigurationView(**asdict(row)) for row in rows[: params.limit]),
            next_cursor=rows[params.limit - 1].assignment_id if len(rows) > params.limit else None,
        )

    async def terms(
        params: Annotated[SupplyConfigurationParams, Query()],
        response: Response,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> TermsConfigurationPageView:
        """Read commercial terms and revisions before replacing terms.

        Requires current operations.manage_terms Party authority. Monetary amount is an
        exact decimal JSON string, not a float. Follow next_cursor as after with the
        same filters. An empty result does not manufacture a new terms revision.
        """
        rows = await reader.read_terms(query(params, current))
        response.headers["Cache-Control"] = "no-store"
        return TermsConfigurationPageView(
            items=tuple(TermsConfigurationView(**asdict(row)) for row in rows[: params.limit]),
            next_cursor=rows[params.limit - 1].context_terms_id
            if len(rows) > params.limit
            else None,
        )

    for path, endpoint, operation_id in (
        ("/v1/booking/resources", resources, "booking_resource_list"),
        ("/v1/operations/resource-assignments", assignments, "booking_resource_assignment_list"),
        ("/v1/operations/context-terms", terms, "booking_context_terms_list"),
    ):
        add_capability_route(
            router,
            path,
            endpoint,
            capability="booking.read_supply",
            methods=["GET"],
            operation_id=operation_id,
        )

    async def availability(
        assignment_id: UUID,
        params: Annotated[SupplyWindowParams, Query()],
        response: Response,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> AvailabilityConfigurationPageView:
        """Read assignment-local weekly availability windows.

        Times are local wall-clock values in the assignment Location's timezone.
        Requires operations.manage_supply Party authority. An empty page does not
        distinguish absent from foreign parents and supplies no parent revision:
        read the assignment first before a revision-sensitive change.
        Follow next_cursor as after with unchanged filters.
        """
        require_capability(current, "booking.read_supply")
        rows = await reader.read_availability(
            SupplyConfigurationQuery(
                current.organization_id,
                current.principal_id,
                params.authority_party_id,
                limit=params.limit,
                after=params.after,
                assignment_id=assignment_id,
            )
        )
        response.headers["Cache-Control"] = "no-store"
        return AvailabilityConfigurationPageView(
            items=tuple(AvailabilityConfigurationView(**asdict(r)) for r in rows[: params.limit]),
            next_cursor=rows[params.limit - 1].window_id if len(rows) > params.limit else None,
        )

    async def assignment_exceptions(
        assignment_id: UUID,
        params: Annotated[SupplyWindowParams, Query()],
        response: Response,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> ExceptionConfigurationPageView:
        """Read assignment-specific schedule exceptions.

        Requires operations.manage_supply Party authority. Empty pages disclose no
        parent existence or revision; read the assignment first before changing it.
        Follow next_cursor as after with unchanged filters.
        """
        require_capability(current, "booking.read_supply")
        rows = await reader.read_exceptions(
            SupplyConfigurationQuery(
                current.organization_id,
                current.principal_id,
                params.authority_party_id,
                limit=params.limit,
                after=params.after,
                assignment_id=assignment_id,
            )
        )
        response.headers["Cache-Control"] = "no-store"
        return ExceptionConfigurationPageView(
            items=tuple(ExceptionConfigurationView(**asdict(r)) for r in rows[: params.limit]),
            next_cursor=rows[params.limit - 1].exception_id if len(rows) > params.limit else None,
        )

    async def resource_exceptions(
        resource_id: UUID,
        params: Annotated[SupplyWindowParams, Query()],
        response: Response,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> ExceptionConfigurationPageView:
        """Read resource-wide schedule exceptions.

        Requires operations.manage_supply Party authority. Empty pages disclose no
        parent existence or revision; read the resource first before changing it.
        Follow next_cursor as after with unchanged filters.
        """
        require_capability(current, "booking.read_supply")
        rows = await reader.read_exceptions(
            SupplyConfigurationQuery(
                current.organization_id,
                current.principal_id,
                params.authority_party_id,
                limit=params.limit,
                after=params.after,
                resource_id=resource_id,
            )
        )
        response.headers["Cache-Control"] = "no-store"
        return ExceptionConfigurationPageView(
            items=tuple(ExceptionConfigurationView(**asdict(r)) for r in rows[: params.limit]),
            next_cursor=rows[params.limit - 1].exception_id if len(rows) > params.limit else None,
        )

    for path, endpoint, operation_id in (
        (
            "/v1/operations/resource-assignments/{assignment_id}/availability",
            availability,
            "booking_resource_assignment_availability_list",
        ),
        (
            "/v1/operations/resource-assignments/{assignment_id}/exceptions",
            assignment_exceptions,
            "booking_resource_assignment_exception_list",
        ),
        (
            "/v1/booking/resources/{resource_id}/exceptions",
            resource_exceptions,
            "booking_resource_exception_list",
        ),
    ):
        add_capability_route(
            router,
            path,
            endpoint,
            capability="booking.read_supply",
            methods=["GET"],
            operation_id=operation_id,
        )
    return router
