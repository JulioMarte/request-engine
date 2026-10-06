from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Query, Request, Response, Security
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field

from request_engine.modules.tenancy.adapters.db.platform_owner_reader import (
    PostgresPlatformOwnerReader,
)
from request_engine.modules.tenancy.application.queries.platform_owner_read import (
    PlatformOwnerReadError,
    PlatformOwnerReadForbidden,
    PlatformOwnerReadNotFound,
    PlatformOwnerReadQuery,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.http.errors import ErrorBody, ErrorEnvelope, ErrorResolution
from request_engine.platform.security.platform_context import PlatformActorContext
from request_engine.platform.security.platform_http import PlatformActorResolver

_Bearer = Annotated[
    HTTPAuthorizationCredentials | None,
    Security(HTTPBearer(scheme_name="NativeSessionBearer", auto_error=False)),
]


class OwnerListParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    after: UUID | None = None
    limit: int = Field(default=50, ge=1, le=100)


class OwnerView(BaseModel):
    principal_id: UUID
    active: bool
    authority_revision: int
    binding_id: UUID | None
    binding_status: str | None
    capabilities: list[str]


class OwnerInvitationView(BaseModel):
    invitation_id: UUID
    status: str
    revision: int
    native_identity_id: UUID | None
    created_at: datetime
    expires_at: datetime
    enrolled_at: datetime | None
    consumed_at: datetime | None
    revoked_at: datetime | None
    expired: bool


class OwnerPageView(BaseModel):
    items: list[OwnerView]
    next_after: UUID | None


class OwnerInvitationPageView(BaseModel):
    items: list[OwnerInvitationView]
    next_after: UUID | None


async def owner_read_error_handler(_: Request, exc: Exception) -> JSONResponse:
    denied = isinstance(exc, PlatformOwnerReadForbidden)
    return JSONResponse(
        status_code=403 if denied else 404,
        content=ErrorEnvelope(
            error=ErrorBody(
                code="platform_owner_read_forbidden" if denied else "platform_owner_not_found",
                message="Owner inspection is not authorized."
                if denied
                else "Owner resource not found.",
                resolution=ErrorResolution.REQUEST_AUTHORITY
                if denied
                else ErrorResolution.FIX_REQUEST,
            )
        ).model_dump(mode="json"),
        headers={"Cache-Control": "no-store"},
    )


def install_platform_owner_reads_http(
    app: FastAPI, *, read_session_factory: SessionFactory, actor_resolver: PlatformActorResolver
) -> None:
    reader = PostgresPlatformOwnerReader(read_session_factory)
    router = APIRouter(tags=["Platform ownership"])

    async def actor(request: Request) -> PlatformActorContext:
        return await actor_resolver.resolve_platform_actor(request)

    async def list_owners(
        params: Annotated[OwnerListParams, Query()],
        actor_context: Annotated[PlatformActorContext, Depends(actor)],
        response: Response,
        _bearer: _Bearer,
    ) -> OwnerPageView:
        rows = await reader.read_owners(
            actor_context, PlatformOwnerReadQuery(after=params.after, limit=params.limit)
        )
        page = rows[: params.limit]
        response.headers["Cache-Control"] = "no-store"
        return OwnerPageView(
            items=[OwnerView.model_validate(row, from_attributes=True) for row in page],
            next_after=page[-1].principal_id if len(rows) > params.limit else None,
        )

    async def get_owner(
        principal_id: UUID,
        actor_context: Annotated[PlatformActorContext, Depends(actor)],
        response: Response,
        _bearer: _Bearer,
    ) -> OwnerView:
        rows = await reader.read_owners(
            actor_context, PlatformOwnerReadQuery(resource_id=principal_id)
        )
        if not rows:
            raise PlatformOwnerReadNotFound()
        response.headers["Cache-Control"] = "no-store"
        return OwnerView.model_validate(rows[0], from_attributes=True)

    async def list_invitations(
        params: Annotated[OwnerListParams, Query()],
        actor_context: Annotated[PlatformActorContext, Depends(actor)],
        response: Response,
        _bearer: _Bearer,
    ) -> OwnerInvitationPageView:
        rows = await reader.read_invitations(
            actor_context, PlatformOwnerReadQuery(after=params.after, limit=params.limit)
        )
        page = rows[: params.limit]
        response.headers["Cache-Control"] = "no-store"
        return OwnerInvitationPageView(
            items=[OwnerInvitationView.model_validate(row, from_attributes=True) for row in page],
            next_after=page[-1].invitation_id if len(rows) > params.limit else None,
        )

    async def get_invitation(
        invitation_id: UUID,
        actor_context: Annotated[PlatformActorContext, Depends(actor)],
        response: Response,
        _bearer: _Bearer,
    ) -> OwnerInvitationView:
        rows = await reader.read_invitations(
            actor_context, PlatformOwnerReadQuery(resource_id=invitation_id)
        )
        if not rows:
            raise PlatformOwnerReadNotFound()
        response.headers["Cache-Control"] = "no-store"
        return OwnerInvitationView.model_validate(rows[0], from_attributes=True)

    for path, endpoint, operation, model in (
        ("/v1/platform/owners", list_owners, "platform_owner_list", OwnerPageView),
        ("/v1/platform/owners/{principal_id}", get_owner, "platform_owner_get", OwnerView),
        (
            "/v1/platform/owner-invitations",
            list_invitations,
            "platform_owner_invitation_list",
            OwnerInvitationPageView,
        ),
        (
            "/v1/platform/owner-invitations/{invitation_id}",
            get_invitation,
            "platform_owner_invitation_get",
            OwnerInvitationView,
        ),
    ):
        add_capability_route(
            router,
            path,
            endpoint,
            capability="platform.owner.read",
            methods=["GET"],
            operation_id=operation,
            owner="tenancy",
            response_model=model,
            responses={status: {"model": ErrorEnvelope} for status in (401, 403, 404, 422)},
        )
    app.add_exception_handler(PlatformOwnerReadError, owner_read_error_handler)
    app.include_router(router)
