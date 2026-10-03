"""Canonical tenant invitation administration and pre-tenant recipient acceptance."""

from collections.abc import Awaitable, Callable
from dataclasses import asdict
from datetime import datetime
from typing import Annotated, Literal, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field

from request_engine.modules.tenancy.api.party_registry_dependencies import IdempotencyKey
from request_engine.modules.tenancy.application.commands.staff_invitations import (
    ChangeStaffInvitationCommand,
    CreateStaffInvitationCommand,
    StaffInvitation,
)
from request_engine.modules.tenancy.application.queries.staff_invitation import (
    StaffInvitationPreview,
)
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.secrets.delivery import RecoveryDeliveryError
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import require_capability
from request_engine.platform.security.subject_http import (
    AuthenticatedHttpSubject,
    HttpSubjectResolver,
)
from request_engine.platform.security.tenant_http import ORGANIZATION_HEADER, TenantContextInvalid


class StaffInvitationCommands(Protocol):
    async def preview(
        self, authenticated: AuthenticatedHttpSubject, invitation_id: UUID, token: str
    ) -> StaffInvitationPreview: ...
    async def list(
        self, actor: ActorContext, *, after: UUID | None, limit: int
    ) -> tuple[StaffInvitation, ...]: ...
    async def get(self, actor: ActorContext, invitation_id: UUID) -> StaffInvitation: ...
    async def create(
        self, actor: ActorContext, command: CreateStaffInvitationCommand
    ) -> StaffInvitation: ...
    async def resend(
        self, actor: ActorContext, command: ChangeStaffInvitationCommand
    ) -> StaffInvitation: ...
    async def revoke(
        self, actor: ActorContext, command: ChangeStaffInvitationCommand
    ) -> StaffInvitation: ...
    async def accept(
        self, authenticated: AuthenticatedHttpSubject, invitation_id: UUID, token: str
    ) -> StaffInvitation: ...


class StaffInvitationCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=320)
    provenance_reference: str = Field(min_length=1, max_length=500)
    expires_in_hours: int = Field(default=72, ge=1, le=168)


class StaffInvitationChangeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    provenance_reference: str = Field(min_length=1, max_length=500)


class StaffInvitationAcceptBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=40, max_length=200, repr=False)


class StaffInvitationView(BaseModel):
    invitation_id: UUID
    organization_id: UUID
    email: str
    status: str
    generation: int
    revision: int
    expires_at: datetime
    created_at: datetime
    membership_id: UUID | None
    principal_id: UUID | None
    binding_id: UUID | None
    delivery_status: str | None


class StaffInvitationPreviewView(BaseModel):
    invitation_id: UUID
    organization_id: UUID
    organization_display_name: str
    status: str
    expires_at: datetime
    requires_acceptance_validation: Literal[True] = True


class StaffInvitationPageView(BaseModel):
    items: list[StaffInvitationView]
    next_after: UUID | None


class StaffInvitationParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    after: UUID | None = None
    limit: int = Field(default=50, ge=1, le=100)


def create_staff_invitation_router(
    *,
    commands: StaffInvitationCommands,
    authenticated_actor: Callable[[Request], Awaitable[ActorContext]],
    subject_resolver: HttpSubjectResolver | None,
) -> APIRouter:
    router = APIRouter(prefix="/v1/staff/invitations", tags=["staff invitations"])

    async def create(
        body: StaffInvitationCreateBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
    ) -> StaffInvitationView:
        require_capability(actor, "staff.invite")
        try:
            result = await commands.create(
                actor,
                CreateStaffInvitationCommand(**body.model_dump(), idempotency_key=idempotency_key),
            )
        except RecoveryDeliveryError:
            raise HTTPException(503, "Staff invitation email delivery is unavailable") from None
        return StaffInvitationView(**asdict(result))

    async def list_invitations(
        params: Annotated[StaffInvitationParams, Query()],
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        response: Response,
    ) -> StaffInvitationPageView:
        require_capability(actor, "staff.read")
        rows = await commands.list(actor, after=params.after, limit=params.limit + 1)
        page = rows[: params.limit]
        response.headers["Cache-Control"] = "no-store"
        return StaffInvitationPageView(
            items=[StaffInvitationView(**asdict(row)) for row in page],
            next_after=page[-1].invitation_id if len(rows) > params.limit else None,
        )

    async def get(
        invitation_id: UUID,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        response: Response,
    ) -> StaffInvitationView:
        require_capability(actor, "staff.read")
        response.headers["Cache-Control"] = "no-store"
        return StaffInvitationView(**asdict(await commands.get(actor, invitation_id)))

    async def resend(
        invitation_id: UUID,
        body: StaffInvitationChangeBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
    ) -> StaffInvitationView:
        require_capability(actor, "staff.invite")
        try:
            result = await commands.resend(
                actor,
                ChangeStaffInvitationCommand(
                    invitation_id=invitation_id,
                    idempotency_key=idempotency_key,
                    **body.model_dump(),
                ),
            )
        except RecoveryDeliveryError:
            raise HTTPException(503, "Staff invitation email delivery is unavailable") from None
        return StaffInvitationView(**asdict(result))

    async def revoke(
        invitation_id: UUID,
        body: StaffInvitationChangeBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
    ) -> StaffInvitationView:
        require_capability(actor, "staff.invite")
        result = await commands.revoke(
            actor,
            ChangeStaffInvitationCommand(
                invitation_id=invitation_id, idempotency_key=idempotency_key, **body.model_dump()
            ),
        )
        return StaffInvitationView(**asdict(result))

    async def subject(
        request: Request,
        _credential: Annotated[
            HTTPAuthorizationCredentials | None,
            Security(HTTPBearer(scheme_name="SubjectBearer", auto_error=False)),
        ],
    ) -> AuthenticatedHttpSubject:
        if ORGANIZATION_HEADER in request.headers:
            raise TenantContextInvalid("Invitation acceptance does not accept a tenant selector")
        if subject_resolver is None:
            raise HTTPException(401, "Subject authentication unavailable")
        return await subject_resolver.resolve_subject(request)

    async def accept(
        invitation_id: UUID,
        body: StaffInvitationAcceptBody,
        authenticated: Annotated[AuthenticatedHttpSubject, Depends(subject)],
        response: Response,
    ) -> StaffInvitationView:
        response.headers["Cache-Control"] = "no-store"
        return StaffInvitationView(
            **asdict(await commands.accept(authenticated, invitation_id, body.token))
        )

    async def preview(
        invitation_id: UUID,
        request: Request,
        body: StaffInvitationAcceptBody,
        authenticated: Annotated[AuthenticatedHttpSubject, Depends(subject)],
        response: Response,
    ) -> StaffInvitationPreviewView:
        if request.query_params:
            raise TenantContextInvalid("Invitation preview does not accept query parameters")
        response.headers["Cache-Control"] = "no-store"
        return StaffInvitationPreviewView(
            **asdict(await commands.preview(authenticated, invitation_id, body.token))
        )

    add_capability_route(
        router,
        "",
        create,
        capability="staff.invite",
        methods=["POST"],
        operation_id="staff_invitation_create",
        response_model=StaffInvitationView,
        status_code=201,
    )
    add_capability_route(
        router,
        "",
        list_invitations,
        capability="staff.read",
        methods=["GET"],
        operation_id="staff_invitation_list",
        response_model=StaffInvitationPageView,
    )
    add_capability_route(
        router,
        "/{invitation_id}",
        get,
        capability="staff.read",
        methods=["GET"],
        operation_id="staff_invitation_get",
        response_model=StaffInvitationView,
    )
    add_capability_route(
        router,
        "/{invitation_id}:resend",
        resend,
        capability="staff.invite",
        methods=["POST"],
        operation_id="staff_invitation_resend",
        response_model=StaffInvitationView,
    )
    add_capability_route(
        router,
        "/{invitation_id}:revoke",
        revoke,
        capability="staff.invite",
        methods=["POST"],
        operation_id="staff_invitation_revoke",
        response_model=StaffInvitationView,
    )
    if subject_resolver is not None:
        router.add_api_route(
            "/{invitation_id}:preview",
            preview,
            methods=["POST"],
            operation_id="staff_invitation_preview",
            response_model=StaffInvitationPreviewView,
            openapi_extra={
                "x-request-engine-owner": "tenancy",
                "x-request-engine-kind": "query",
                "x-request-engine-idempotency": "none",
                "x-request-engine-authentication": "native-human-subject",
            },
        )
        router.add_api_route(
            "/{invitation_id}:accept",
            accept,
            methods=["POST"],
            operation_id="staff_invitation_accept",
            response_model=StaffInvitationView,
            openapi_extra={
                "x-request-engine-owner": "tenancy",
                "x-request-engine-kind": "command",
                "x-request-engine-idempotency": "subject-bound-acceptance-replay",
                "x-request-engine-authentication": "native-human-subject",
            },
        )
    return router
