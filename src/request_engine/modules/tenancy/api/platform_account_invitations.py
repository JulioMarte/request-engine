"""Private control-plane owner account invitations (ADR 0021)."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Header, Query, Request, Response, Security
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field

from request_engine.modules.tenancy.adapters.db.account_invitation_commands import (
    PostgresPlatformAccountInvitationCommands,
)
from request_engine.modules.tenancy.application.commands.account_invitations import (
    AccountInvitationConflict,
    AccountInvitationDeliveryUnavailable,
    AccountInvitationError,
    AccountInvitationForbidden,
    AccountInvitationInvalid,
    AccountInvitationMailer,
    AccountInvitationNotFound,
    AccountInvitationRevisionConflict,
    AccountInvitationSummary,
    CreateAccountInvitationCommand,
    RevokeAccountInvitationCommand,
)
from request_engine.modules.tenancy.domain.account_entitlement import (
    AccountInvitationDelivery,
    AccountRuleViolation,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.http.errors import ErrorBody, ErrorEnvelope, ErrorResolution
from request_engine.platform.security.platform_context import PlatformActorContext
from request_engine.platform.security.platform_http import PlatformActorResolver

_NativeBearer = Annotated[
    HTTPAuthorizationCredentials | None,
    Security(HTTPBearer(scheme_name="NativeSessionBearer", auto_error=False)),
]
_IdempotencyKey = Annotated[
    str, Header(alias="Idempotency-Key", min_length=1, max_length=200, pattern=r"\S")
]


class AccountInvitationCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    delivery: Literal["email", "shared_code"]
    email: str | None = Field(default=None, min_length=3, max_length=254)
    max_organizations: int = Field(default=1, ge=1, le=10)
    expires_in_hours: int = Field(default=72, ge=1, le=168)
    provenance_reference: str = Field(min_length=1, max_length=500)


class AccountInvitationCreatedView(BaseModel):
    invitation_id: UUID
    status: str
    revision: int
    delivery: str
    delivery_status: str | None
    max_organizations: int
    expires_at: datetime
    invitation_token: str | None = Field(
        description="Only for shared_code on the first successful creation; never stored."
    )
    token_available: bool


class AccountInvitationRevokeBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_revision: int = Field(ge=1)
    reason_code: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_]*$")


class AccountInvitationRevokedView(BaseModel):
    invitation_id: UUID
    status: str
    revision: int


class AccountInvitationView(BaseModel):
    invitation_id: UUID
    delivery: str
    email: str | None
    max_organizations: int
    status: str
    expired: bool
    revision: int
    delivery_status: str | None
    invited_by_principal_id: UUID
    native_identity_id: UUID | None
    entitlement_id: UUID | None
    organizations_created: int | None
    created_at: datetime
    expires_at: datetime
    accepted_at: datetime | None
    revoked_at: datetime | None


class AccountInvitationPageView(BaseModel):
    items: list[AccountInvitationView]
    next_after: UUID | None


class AccountInvitationListParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    after: UUID | None = None
    limit: int = Field(default=50, ge=1, le=100)


_ERRORS: dict[type[Exception], tuple[int, str, ErrorResolution, bool]] = {
    AccountInvitationForbidden: (
        403,
        "account_invitation_forbidden",
        ErrorResolution.REQUEST_AUTHORITY,
        False,
    ),
    AccountInvitationConflict: (
        409,
        "account_invitation_conflict",
        ErrorResolution.REFRESH_AND_RETRY,
        False,
    ),
    AccountInvitationRevisionConflict: (
        409,
        "account_invitation_revision_conflict",
        ErrorResolution.REFRESH_AND_RETRY,
        False,
    ),
    AccountInvitationInvalid: (
        422,
        "account_invitation_invalid",
        ErrorResolution.FIX_REQUEST,
        False,
    ),
    AccountInvitationNotFound: (
        404,
        "account_invitation_not_found",
        ErrorResolution.FIX_REQUEST,
        False,
    ),
    AccountInvitationDeliveryUnavailable: (
        503,
        "account_invitation_delivery_unavailable",
        ErrorResolution.OPERATOR_INTERVENTION,
        False,
    ),
}


async def platform_account_invitation_error_handler(_: Request, exc: Exception) -> JSONResponse:
    status_code, code, resolution, retryable = _ERRORS.get(
        type(exc),
        (500, "account_invitation_failed", ErrorResolution.OPERATOR_INTERVENTION, False),
    )
    return JSONResponse(
        status_code=status_code,
        content=ErrorEnvelope(
            error=ErrorBody(
                code=code,
                message="The account invitation operation could not be accepted.",
                resolution=resolution,
                retryable=retryable,
            )
        ).model_dump(mode="json"),
        headers={"Cache-Control": "no-store"},
    )


def _view(row: AccountInvitationSummary) -> AccountInvitationView:
    return AccountInvitationView(
        invitation_id=row.invitation_id,
        delivery=row.delivery,
        email=row.email,
        max_organizations=row.max_organizations,
        status=row.status,
        expired=row.expired,
        revision=row.revision,
        delivery_status=row.delivery_status,
        invited_by_principal_id=row.invited_by_principal_id,
        native_identity_id=row.native_identity_id,
        entitlement_id=row.entitlement_id,
        organizations_created=row.organizations_created,
        created_at=row.created_at,
        expires_at=row.expires_at,
        accepted_at=row.accepted_at,
        revoked_at=row.revoked_at,
    )


def install_platform_account_invitations_http(
    app: FastAPI,
    *,
    write_session_factory: SessionFactory,
    read_session_factory: SessionFactory,
    actor_resolver: PlatformActorResolver,
    mailer: AccountInvitationMailer | None,
) -> None:
    commands = PostgresPlatformAccountInvitationCommands(
        write_session_factory, read_session_factory, mailer=mailer
    )
    router = APIRouter(tags=["Platform account invitations"])

    async def authenticated_actor(request: Request) -> PlatformActorContext:
        return await actor_resolver.resolve_platform_actor(request)

    async def create(
        body: AccountInvitationCreateBody,
        actor: Annotated[PlatformActorContext, Depends(authenticated_actor)],
        _bearer: _NativeBearer,
        idempotency_key: _IdempotencyKey,
        response: Response,
    ) -> AccountInvitationCreatedView:
        try:
            command = CreateAccountInvitationCommand(
                delivery=AccountInvitationDelivery(body.delivery),
                email=body.email,
                max_organizations=body.max_organizations,
                expires_in_hours=body.expires_in_hours,
                provenance_reference=body.provenance_reference,
                idempotency_key=idempotency_key,
            )
        except (AccountRuleViolation, ValueError) as exc:
            raise AccountInvitationInvalid(str(exc)) from None
        result = await commands.create(actor, command)
        response.headers["Cache-Control"] = "no-store"
        return AccountInvitationCreatedView(
            invitation_id=result.invitation_id,
            status=result.status,
            revision=result.revision,
            delivery=body.delivery,
            delivery_status=result.delivery_status,
            max_organizations=body.max_organizations,
            expires_at=result.expires_at,
            invitation_token=result.raw_token,
            token_available=result.raw_token is not None,
        )

    async def list_invitations(
        params: Annotated[AccountInvitationListParams, Query()],
        actor: Annotated[PlatformActorContext, Depends(authenticated_actor)],
        _bearer: _NativeBearer,
        response: Response,
    ) -> AccountInvitationPageView:
        rows = await commands.list(
            actor, invitation_id=None, after=params.after, limit=params.limit
        )
        page = rows[: params.limit]
        response.headers["Cache-Control"] = "no-store"
        return AccountInvitationPageView(
            items=[_view(row) for row in page],
            next_after=page[-1].invitation_id if len(rows) > params.limit else None,
        )

    async def get_invitation(
        invitation_id: UUID,
        actor: Annotated[PlatformActorContext, Depends(authenticated_actor)],
        _bearer: _NativeBearer,
        response: Response,
    ) -> AccountInvitationView:
        rows = await commands.list(actor, invitation_id=invitation_id, after=None, limit=1)
        if not rows:
            raise AccountInvitationNotFound()
        response.headers["Cache-Control"] = "no-store"
        return _view(rows[0])

    async def revoke(
        invitation_id: UUID,
        body: AccountInvitationRevokeBody,
        actor: Annotated[PlatformActorContext, Depends(authenticated_actor)],
        _bearer: _NativeBearer,
        idempotency_key: _IdempotencyKey,
    ) -> AccountInvitationRevokedView:
        result = await commands.revoke(
            actor,
            RevokeAccountInvitationCommand(
                invitation_id=invitation_id,
                expected_revision=body.expected_revision,
                reason_code=body.reason_code,
                idempotency_key=idempotency_key,
            ),
        )
        return AccountInvitationRevokedView(
            invitation_id=result.invitation_id, status=result.status, revision=result.revision
        )

    mutation = {status: {"model": ErrorEnvelope} for status in (400, 401, 403, 409, 422)}
    add_capability_route(
        router,
        "/v1/platform/account-invitations",
        create,
        capability="organization.provision",
        methods=["POST"],
        operation_id="platform_account_invitation_create",
        owner="tenancy",
        status_code=201,
        response_model=AccountInvitationCreatedView,
        summary="Invite a business owner to self-enroll and create their businesses",
        description="shared_code returns the one-time code once (share it by WhatsApp); "
        "email sends it after commit and never returns it. Email without a configured "
        "mailer returns 503 account_invitation_delivery_unavailable and creates nothing.",
        responses={**mutation, 503: {"model": ErrorEnvelope}},
    )
    add_capability_route(
        router,
        "/v1/platform/account-invitations",
        list_invitations,
        capability="platform.organization.read",
        methods=["GET"],
        operation_id="platform_account_invitation_list",
        owner="tenancy",
        response_model=AccountInvitationPageView,
        responses={status: {"model": ErrorEnvelope} for status in (401, 403, 422)},
    )
    add_capability_route(
        router,
        "/v1/platform/account-invitations/{invitation_id}",
        get_invitation,
        capability="platform.organization.read",
        methods=["GET"],
        operation_id="platform_account_invitation_get",
        owner="tenancy",
        response_model=AccountInvitationView,
        responses={status: {"model": ErrorEnvelope} for status in (401, 403, 404, 422)},
    )
    add_capability_route(
        router,
        "/v1/platform/account-invitations/{invitation_id}:revoke",
        revoke,
        capability="organization.provision",
        methods=["POST"],
        operation_id="platform_account_invitation_revoke",
        owner="tenancy",
        response_model=AccountInvitationRevokedView,
        responses={**mutation, 404: {"model": ErrorEnvelope}},
    )
    app.add_exception_handler(AccountInvitationError, platform_account_invitation_error_handler)
    app.include_router(router)
