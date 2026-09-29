from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Query, Request, Response
from fastapi import status as http_status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from request_engine.modules.tenancy.adapters.db.platform_organization_reader import (
    PostgresPlatformOrganizationReader,
)
from request_engine.modules.tenancy.application.queries.platform_organization_read import (
    PLATFORM_ORGANIZATION_READ_CAPABILITY,
    GetPlatformOrganizationQuery,
    ListPlatformOrganizationsQuery,
    PlatformOrganizationReader,
    PlatformOrganizationReadError,
    PlatformOrganizationReadForbidden,
    PlatformOrganizationReadInvalid,
    PlatformOrganizationReadNotFound,
    PlatformOrganizationSummary,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.http.errors import ErrorBody, ErrorEnvelope, ErrorResolution
from request_engine.platform.security.platform_context import PlatformActorContext
from request_engine.platform.security.platform_http import PlatformActorResolver


class PlatformOrganizationView(BaseModel):
    organization_id: UUID
    organization_key: str
    display_name: str
    operational_status: str
    default_timezone: str | None
    default_locale: str | None
    default_currency: str | None
    created_at: datetime
    updated_at: datetime


class PlatformOrganizationPageView(BaseModel):
    items: list[PlatformOrganizationView]
    next_after: UUID | None


class PlatformOrganizationListParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    after: UUID | None = None
    limit: int = Field(default=50, ge=1, le=100)


def add_platform_organization_reads(
    router: APIRouter,
    *,
    reader: PlatformOrganizationReader,
    authenticated_actor: Callable[[Request], Awaitable[PlatformActorContext]],
) -> None:
    async def list_organizations(
        params: Annotated[PlatformOrganizationListParams, Query()],
        actor: Annotated[PlatformActorContext, Depends(authenticated_actor)],
        response: Response,
    ) -> PlatformOrganizationPageView:
        rows = await reader.list_organizations(
            actor, ListPlatformOrganizationsQuery(after=params.after, limit=params.limit)
        )
        response.headers["Cache-Control"] = "no-store"
        return PlatformOrganizationPageView(
            items=[_view(row) for row in rows],
            next_after=rows[-1].organization_id if len(rows) == params.limit else None,
        )

    async def get_organization(
        organization_id: UUID,
        actor: Annotated[PlatformActorContext, Depends(authenticated_actor)],
        response: Response,
    ) -> PlatformOrganizationView:
        row = await reader.get_organization(actor, GetPlatformOrganizationQuery(organization_id))
        response.headers["Cache-Control"] = "no-store"
        return _view(row)

    read_responses = {status: {"model": ErrorEnvelope} for status in (401, 403, 422)}
    add_capability_route(
        router,
        "/v1/platform/organizations",
        list_organizations,
        capability=PLATFORM_ORGANIZATION_READ_CAPABILITY,
        methods=["GET"],
        operation_id="platform_organization_list",
        owner="tenancy",
        response_model=PlatformOrganizationPageView,
        responses=read_responses,
    )
    add_capability_route(
        router,
        "/v1/platform/organizations/{organization_id}",
        get_organization,
        capability=PLATFORM_ORGANIZATION_READ_CAPABILITY,
        methods=["GET"],
        operation_id="platform_organization_get",
        owner="tenancy",
        response_model=PlatformOrganizationView,
        responses={**read_responses, 404: {"model": ErrorEnvelope}},
    )


def install_platform_organization_reads_http(
    app: FastAPI,
    *,
    read_session_factory: SessionFactory,
    actor_resolver: PlatformActorResolver,
) -> None:
    router = APIRouter(tags=["Platform provisioning"])

    async def authenticated_actor(request: Request) -> PlatformActorContext:
        return await actor_resolver.resolve_platform_actor(request)

    add_platform_organization_reads(
        router,
        reader=PostgresPlatformOrganizationReader(read_session_factory),
        authenticated_actor=authenticated_actor,
    )
    app.add_exception_handler(PlatformOrganizationReadError, platform_organization_error_handler)
    app.include_router(router)


async def platform_organization_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, PlatformOrganizationReadForbidden):
        status_code = http_status.HTTP_403_FORBIDDEN
        body = ErrorBody(
            code="platform_organization_read_forbidden",
            message="the current operator may not inspect organizations",
            resolution=ErrorResolution.REQUEST_AUTHORITY,
        )
    elif isinstance(exc, PlatformOrganizationReadNotFound):
        status_code = http_status.HTTP_404_NOT_FOUND
        body = ErrorBody(
            code="platform_organization_not_found",
            message="organization was not found",
            resolution=ErrorResolution.FIX_REQUEST,
        )
    elif isinstance(exc, PlatformOrganizationReadInvalid):
        status_code = http_status.HTTP_422_UNPROCESSABLE_CONTENT
        body = ErrorBody(
            code="platform_organization_read_invalid",
            message="the organization query is invalid",
            resolution=ErrorResolution.FIX_REQUEST,
        )
    else:
        status_code = http_status.HTTP_500_INTERNAL_SERVER_ERROR
        body = ErrorBody(
            code="platform_organization_read_failed",
            message="the organization read failed",
            resolution=ErrorResolution.OPERATOR_INTERVENTION,
        )
    return JSONResponse(
        status_code=status_code,
        content=ErrorEnvelope(error=body).model_dump(mode="json"),
        headers={"Cache-Control": "no-store"},
    )


def _view(row: PlatformOrganizationSummary) -> PlatformOrganizationView:
    return PlatformOrganizationView(
        organization_id=row.organization_id,
        organization_key=row.organization_key,
        display_name=row.display_name,
        operational_status=row.operational_status,
        default_timezone=row.default_timezone,
        default_locale=row.default_locale,
        default_currency=row.default_currency,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
