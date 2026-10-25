"""Runtime self-service owner account HTTP surface (ADR 0021).

Public invitation enrollment plus two pre-tenant native-session operations. None of
them accepts a tenant selector and none of them grants tenant authority by itself.
"""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Header, Request, Response, Security
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field

from request_engine.modules.tenancy.application.commands.account_invitations import (
    AccountEnrollmentUnavailable,
    AccountInvitationEnrollmentCommands,
    AccountInvitationError,
    AccountInvitationInvalid,
    AccountLoginUnavailable,
    AccountPasswordInvalid,
    EnrollAccountInvitationCommand,
)
from request_engine.modules.tenancy.application.commands.self_service_organizations import (
    CreateSelfServiceOrganizationCommand,
    SelfServiceAccountCommands,
    SelfServiceOrganizationError,
    SelfServiceOrganizationForbidden,
    SelfServiceOrganizationIdempotencyConflict,
    SelfServiceOrganizationInvalid,
    SelfServiceOrganizationKeyUnavailable,
    SelfServiceOrganizationLimitReached,
)
from request_engine.modules.tenancy.domain.account_entitlement import (
    ACCOUNT_ORGANIZATION_CREATE,
    DEFAULT_CURRENCY,
    DEFAULT_LOCALE,
    DEFAULT_TIMEZONE,
    AccountRuleViolation,
)
from request_engine.platform.http.errors import ErrorBody, ErrorEnvelope, ErrorResolution
from request_engine.platform.security.authentication import AuthenticatedSubjectClass
from request_engine.platform.security.freshness import RecoveryCompletionRequired
from request_engine.platform.security.http import AuthenticationRequired, request_correlation_id
from request_engine.platform.security.native_auth import normalize_login_handle
from request_engine.platform.security.subject_http import (
    AuthenticatedHttpSubject,
    HttpSubjectResolver,
)
from request_engine.platform.security.tenant_http import ORGANIZATION_HEADER, TenantContextInvalid

ENROLL_PATH = "/v1/account-invitations:enroll"


class AccountInvitationEnrollBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    invitation_token: str = Field(min_length=20, max_length=200, repr=False)
    login_handle: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=1024, repr=False)


class OrganizationCreationEntitlementView(BaseModel):
    entitlement_id: UUID
    entitlement: Literal["account.organization.create"] = ACCOUNT_ORGANIZATION_CREATE
    status: str
    max_organizations: int
    organizations_created: int
    remaining: int


class AccountInvitationEnrollView(BaseModel):
    invitation_id: UUID
    native_identity_id: UUID
    login_handle: str
    organization_creation: OrganizationCreationEntitlementView


class SelfAccountView(BaseModel):
    native_identity_id: UUID
    organization_creation: OrganizationCreationEntitlementView | None
    requires_owner_validation: Literal[True] = True


class SelfOrganizationCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    display_name: str = Field(min_length=1, max_length=200)
    organization_key: str | None = Field(default=None, min_length=3, max_length=63)
    timezone: str = Field(default=DEFAULT_TIMEZONE, min_length=1, max_length=64)
    locale: str = Field(default=DEFAULT_LOCALE, min_length=2, max_length=6)
    currency: str = Field(default=DEFAULT_CURRENCY, min_length=3, max_length=3)


class SelfOrganizationCreatedView(BaseModel):
    organization_id: UUID
    organization_party_id: UUID
    controller_principal_id: UUID
    controller_binding_id: UUID
    membership_id: UUID | None
    organization_key: str
    display_name: str
    default_timezone: str
    default_locale: str
    default_currency: str
    initial_controller_policy: str
    organization_creation: OrganizationCreationEntitlementView


_ERRORS: dict[type[Exception], tuple[int, str, ErrorResolution]] = {
    AccountInvitationInvalid: (422, "account_invitation_invalid", ErrorResolution.FIX_REQUEST),
    AccountPasswordInvalid: (422, "account_password_invalid", ErrorResolution.FIX_REQUEST),
    AccountLoginUnavailable: (409, "account_login_unavailable", ErrorResolution.FIX_REQUEST),
    AccountEnrollmentUnavailable: (
        503,
        "native_enrollment_unavailable",
        ErrorResolution.OPERATOR_INTERVENTION,
    ),
    SelfServiceOrganizationForbidden: (
        403,
        "account_organization_creation_forbidden",
        ErrorResolution.REQUEST_AUTHORITY,
    ),
    SelfServiceOrganizationLimitReached: (
        409,
        "account_organization_limit_reached",
        ErrorResolution.REQUEST_AUTHORITY,
    ),
    SelfServiceOrganizationKeyUnavailable: (
        409,
        "organization_key_unavailable",
        ErrorResolution.FIX_REQUEST,
    ),
    SelfServiceOrganizationIdempotencyConflict: (
        409,
        "idempotency_key_conflict",
        ErrorResolution.FIX_REQUEST,
    ),
    SelfServiceOrganizationInvalid: (
        422,
        "account_organization_invalid",
        ErrorResolution.FIX_REQUEST,
    ),
}


async def self_service_account_error_handler(_: Request, exc: Exception) -> JSONResponse:
    status_code, code, resolution = _ERRORS.get(
        type(exc), (500, "self_service_account_failed", ErrorResolution.OPERATOR_INTERVENTION)
    )
    return JSONResponse(
        status_code=status_code,
        content=ErrorEnvelope(
            error=ErrorBody(
                code=code,
                message="The self-service account operation could not be accepted.",
                resolution=resolution,
                retryable=False,
            )
        ).model_dump(mode="json"),
        headers={"Cache-Control": "no-store"},
    )


def _entitlement_view(
    entitlement_id: UUID, status: str, maximum: int, created: int
) -> OrganizationCreationEntitlementView:
    return OrganizationCreationEntitlementView(
        entitlement_id=entitlement_id,
        status=status,
        max_organizations=maximum,
        organizations_created=created,
        remaining=max(0, maximum - created) if status == "active" else 0,
    )


def install_self_service_account_http(
    app: FastAPI,
    *,
    commands: SelfServiceAccountCommands,
    enrollment: AccountInvitationEnrollmentCommands,
    subject_resolver: HttpSubjectResolver,
) -> None:
    router = APIRouter(tags=["Self-service accounts"])

    async def native_subject(
        request: Request,
        _credential: Annotated[
            HTTPAuthorizationCredentials | None,
            Security(HTTPBearer(scheme_name="NativeSessionBearer", auto_error=False)),
        ],
    ) -> AuthenticatedHttpSubject:
        if ORGANIZATION_HEADER in request.headers:
            raise TenantContextInvalid("Self-service accounts do not accept a tenant selector")
        if request.query_params:
            raise TenantContextInvalid("Self-service accounts do not accept query parameters")
        authenticated = await subject_resolver.resolve_subject(request)
        if authenticated.subject.subject_class is not AuthenticatedSubjectClass.HUMAN:
            raise AuthenticationRequired("Human authentication is required")
        if authenticated.subject.metadata.get("recovery_restricted", "").lower() == "true":
            raise RecoveryCompletionRequired("Complete identity recovery first")
        return authenticated

    async def enroll(
        body: AccountInvitationEnrollBody, request: Request, response: Response
    ) -> AccountInvitationEnrollView:
        if ORGANIZATION_HEADER in request.headers or request.query_params:
            raise TenantContextInvalid("Invitation enrollment accepts only its JSON body")
        try:
            command = EnrollAccountInvitationCommand(
                raw_token=body.invitation_token,
                login_handle=normalize_login_handle(body.login_handle),
                password=body.password,
            )
        except ValueError as exc:
            raise AccountInvitationInvalid(str(exc)) from None
        result = await enrollment.enroll(command)
        response.headers["Cache-Control"] = "no-store"
        return AccountInvitationEnrollView(
            invitation_id=result.invitation_id,
            native_identity_id=result.native_identity_id,
            login_handle=result.login_handle,
            organization_creation=_entitlement_view(
                result.entitlement_id, "active", result.max_organizations, 0
            ),
        )

    async def read_account(
        authenticated: Annotated[AuthenticatedHttpSubject, Depends(native_subject)],
        response: Response,
    ) -> SelfAccountView:
        entitlement = await commands.read_entitlement(authenticated)
        response.headers["Cache-Control"] = "no-store"
        return SelfAccountView(
            native_identity_id=UUID(authenticated.subject.subject_id),
            organization_creation=None
            if entitlement is None
            else _entitlement_view(
                entitlement.entitlement_id,
                entitlement.status,
                entitlement.max_organizations,
                entitlement.organizations_created,
            ),
        )

    async def create_organization(
        body: SelfOrganizationCreateBody,
        request: Request,
        authenticated: Annotated[AuthenticatedHttpSubject, Depends(native_subject)],
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=1, max_length=200, pattern=r"\S")
        ],
        response: Response,
    ) -> SelfOrganizationCreatedView:
        try:
            command = CreateSelfServiceOrganizationCommand(
                display_name=body.display_name,
                organization_key=body.organization_key,
                timezone=body.timezone,
                locale=body.locale,
                currency=body.currency,
                idempotency_key=idempotency_key,
            )
        except (AccountRuleViolation, ValueError) as exc:
            raise SelfServiceOrganizationInvalid(str(exc)) from None
        result = await commands.create_organization(
            authenticated, command, correlation_id=request_correlation_id(request)
        )
        response.headers["Cache-Control"] = "no-store"
        return SelfOrganizationCreatedView(
            organization_id=result.organization_id,
            organization_party_id=result.organization_party_id,
            controller_principal_id=result.controller_principal_id,
            controller_binding_id=result.controller_binding_id,
            membership_id=result.membership_id,
            organization_key=result.organization_key,
            display_name=result.display_name,
            default_timezone=result.default_timezone,
            default_locale=result.default_locale,
            default_currency=result.default_currency,
            initial_controller_policy=result.initial_controller_policy,
            organization_creation=_entitlement_view(
                result.entitlement_id,
                "active",
                result.max_organizations,
                result.organizations_created,
            ),
        )

    router.add_api_route(
        ENROLL_PATH,
        enroll,
        methods=["POST"],
        operation_id="account_invitation_enroll",
        status_code=201,
        response_model=AccountInvitationEnrollView,
        summary="Enroll your own native identity with an owner account invitation code",
        description="Public, rate-limited as an authentication attempt. The invitee chooses "
        "the login handle and password (native password policy). Unknown, expired, revoked "
        "and used codes are indistinguishable (422). Creates no Principal, membership or "
        "session: sign in afterwards with POST /auth/native/sessions.",
        responses={status: {"model": ErrorEnvelope} for status in (400, 409, 422, 429, 503)},
        openapi_extra={
            "x-request-engine-owner": "tenancy",
            "x-request-engine-kind": "command",
            "x-request-engine-idempotency": "single-use-invitation-code",
            "x-request-engine-authentication": "invitation-code",
        },
    )
    router.add_api_route(
        "/v1/me/account",
        read_account,
        methods=["GET"],
        operation_id="self_account_get",
        response_model=SelfAccountView,
        summary="Read the caller's account entitlement to create organizations",
        responses={status: {"model": ErrorEnvelope} for status in (400, 401, 403)},
        openapi_extra={
            "x-request-engine-owner": "tenancy",
            "x-request-engine-kind": "query",
            "x-request-engine-idempotency": "none",
            "x-request-engine-authentication": "native-human-subject",
            "x-request-engine-native-session": True,
        },
    )
    router.add_api_route(
        "/v1/me/organizations",
        create_organization,
        methods=["POST"],
        operation_id="self_organization_create",
        status_code=201,
        response_model=SelfOrganizationCreatedView,
        summary="Create an organization you control with your account entitlement",
        description="Requires a normal native session and an active "
        "account.organization.create entitlement with remaining capacity. Creates the "
        "organization, its Party and you as root controller (current initial controller "
        "policy) atomically. Idempotency-Key required: same key and body replays the "
        "original receipt; a different body returns 409.",
        responses={status: {"model": ErrorEnvelope} for status in (400, 401, 403, 409, 422)},
        openapi_extra={
            "x-request-engine-owner": "tenancy",
            "x-request-engine-kind": "command",
            "x-request-engine-idempotency": "required",
            "x-request-engine-authentication": "native-human-subject",
            "x-request-engine-entitlement": ACCOUNT_ORGANIZATION_CREATE,
            "x-request-engine-native-session": True,
        },
    )
    for error in (AccountInvitationError, SelfServiceOrganizationError):
        app.add_exception_handler(error, self_service_account_error_handler)
    app.include_router(router)
