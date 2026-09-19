from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Header, Request, Security
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field

from request_engine.modules.tenancy.adapters.db.platform_owner_commands import (
    PostgresPlatformOwnerCommands,
)
from request_engine.modules.tenancy.application.commands.platform_owner_lifecycle import (
    ActivatePlatformOwnerInvitationCommand,
    CreatePlatformOwnerInvitationCommand,
    EnrollPlatformOwnerInvitationCommand,
    PlatformOwnerConflict,
    PlatformOwnerError,
    PlatformOwnerForbidden,
    PlatformOwnerInvalid,
    PlatformOwnerLifecycleAction,
    PlatformOwnerRevisionConflict,
    TransitionPlatformOwnerCommand,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.http.errors import (
    ErrorBody,
    ErrorEnvelope,
    ErrorResolution,
)
from request_engine.platform.security.freshness import (
    require_phishing_resistant_authentication,
)
from request_engine.platform.security.native_auth import (
    PasswordPolicyViolation,
    normalize_login_handle,
)
from request_engine.platform.security.platform_context import PlatformActorContext
from request_engine.platform.security.platform_http import PlatformActorResolver

_NativeBearer = Annotated[
    HTTPAuthorizationCredentials | None,
    Security(HTTPBearer(scheme_name="NativeSessionBearer", auto_error=False)),
]
_IdempotencyKey = Annotated[
    str, Header(alias="Idempotency-Key", min_length=1, max_length=200, pattern=r"\S")
]


class PlatformOwnerInvitationCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    provenance_reference: str = Field(min_length=1, max_length=500)


class PlatformOwnerInvitationView(BaseModel):
    invitation_id: UUID
    invitation_token: str | None
    expires_at: datetime
    token_available: bool


class PlatformOwnerInvitationEnrollBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    invitation_token: str = Field(min_length=20, max_length=1024, repr=False)
    login_handle: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=1024, repr=False)


class PlatformOwnerInvitationEnrollView(BaseModel):
    invitation_id: UUID
    native_identity_id: UUID


class PlatformOwnerProvisionView(BaseModel):
    principal_id: UUID
    binding_id: UUID


class PlatformOwnerLifecycleBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_revision: int = Field(ge=1)
    reason_code: str = Field(min_length=1, max_length=80)
    external_case_reference: str | None = Field(default=None, min_length=1, max_length=200)


class PlatformOwnerLifecycleView(BaseModel):
    fact_id: UUID
    principal_id: UUID
    action: str
    authority_revision: int
    binding_id: UUID | None
    binding_status: str | None


async def platform_owner_error_handler(_: Request, exc: Exception) -> JSONResponse:
    errors: dict[type[Exception], tuple[int, str, ErrorResolution]] = {
        PlatformOwnerForbidden: (
            403,
            "platform_owner_forbidden",
            ErrorResolution.REQUEST_AUTHORITY,
        ),
        PlatformOwnerConflict: (
            409,
            "platform_owner_conflict",
            ErrorResolution.REFRESH_AND_RETRY,
        ),
        PlatformOwnerInvalid: (
            422,
            "platform_owner_invalid",
            ErrorResolution.FIX_REQUEST,
        ),
        PlatformOwnerRevisionConflict: (
            409,
            "platform_authority_changed",
            ErrorResolution.REFRESH_AND_RETRY,
        ),
    }
    status_code, code, resolution = errors.get(
        type(exc),
        (
            500,
            "platform_owner_management_failed",
            ErrorResolution.OPERATOR_INTERVENTION,
        ),
    )
    return JSONResponse(
        status_code=status_code,
        content=ErrorEnvelope(
            error=ErrorBody(
                code=code,
                message="The Platform Owner operation could not be accepted.",
                resolution=resolution,
                retryable=False,
            )
        ).model_dump(mode="json"),
        headers={"Cache-Control": "no-store"},
    )


def install_platform_owner_management_http(
    app: FastAPI,
    *,
    write_session_factory: SessionFactory,
    actor_resolver: PlatformActorResolver,
    native_authority_id: UUID,
) -> None:
    commands = PostgresPlatformOwnerCommands(
        write_session_factory,
        native_authority_id=native_authority_id,
    )
    router = APIRouter(tags=["Platform Owners"])

    async def authenticated_actor(request: Request) -> PlatformActorContext:
        return await actor_resolver.resolve_platform_actor(request)

    async def create_invitation(
        body: PlatformOwnerInvitationCreateBody,
        actor: Annotated[PlatformActorContext, Depends(authenticated_actor)],
        _bearer: _NativeBearer,
        idempotency_key: _IdempotencyKey,
    ) -> PlatformOwnerInvitationView:
        require_phishing_resistant_authentication(actor, now=datetime.now(UTC))
        result = await commands.create_invitation(
            actor,
            CreatePlatformOwnerInvitationCommand(
                provenance_reference=body.provenance_reference,
                idempotency_key=idempotency_key,
            ),
        )
        return PlatformOwnerInvitationView(
            invitation_id=result.invitation_id,
            invitation_token=result.raw_token,
            expires_at=result.expires_at,
            token_available=result.created,
        )

    async def enroll_invitation(
        body: PlatformOwnerInvitationEnrollBody,
    ) -> PlatformOwnerInvitationEnrollView:
        try:
            command = EnrollPlatformOwnerInvitationCommand(
                raw_token=body.invitation_token,
                login_handle=normalize_login_handle(body.login_handle),
                password=body.password,
            )
            result = await commands.enroll_invitation(command)
        except PasswordPolicyViolation as exc:
            raise PlatformOwnerInvalid("invitation password is invalid") from exc
        return PlatformOwnerInvitationEnrollView(
            invitation_id=result.invitation_id,
            native_identity_id=result.native_identity_id,
        )

    async def activate_invitation(
        invitation_id: UUID,
        actor: Annotated[PlatformActorContext, Depends(authenticated_actor)],
        _bearer: _NativeBearer,
        idempotency_key: _IdempotencyKey,
    ) -> PlatformOwnerProvisionView:
        require_phishing_resistant_authentication(actor, now=datetime.now(UTC))
        result = await commands.activate_invitation(
            actor,
            ActivatePlatformOwnerInvitationCommand(
                invitation_id=invitation_id,
                idempotency_key=idempotency_key,
            ),
        )
        return PlatformOwnerProvisionView(
            principal_id=result.principal_id,
            binding_id=result.binding_id,
        )

    async def transition(
        principal_id: UUID,
        action: PlatformOwnerLifecycleAction,
        body: PlatformOwnerLifecycleBody,
        actor: PlatformActorContext,
        idempotency_key: str,
    ) -> PlatformOwnerLifecycleView:
        require_phishing_resistant_authentication(actor, now=datetime.now(UTC))
        result = await commands.transition_owner(
            actor,
            TransitionPlatformOwnerCommand(
                principal_id=principal_id,
                action=action,
                expected_revision=body.expected_revision,
                reason_code=body.reason_code,
                idempotency_key=idempotency_key,
                external_case_reference=body.external_case_reference,
            ),
        )
        return PlatformOwnerLifecycleView(
            fact_id=result.fact_id,
            principal_id=result.principal_id,
            action=result.action.value,
            authority_revision=result.authority_revision,
            binding_id=result.binding_id,
            binding_status=result.binding_status,
        )

    async def suspend_owner(
        principal_id: UUID,
        body: PlatformOwnerLifecycleBody,
        actor: Annotated[PlatformActorContext, Depends(authenticated_actor)],
        _bearer: _NativeBearer,
        idempotency_key: _IdempotencyKey,
    ) -> PlatformOwnerLifecycleView:
        return await transition(
            principal_id,
            PlatformOwnerLifecycleAction.SUSPEND,
            body,
            actor,
            idempotency_key,
        )

    async def reactivate_owner(
        principal_id: UUID,
        body: PlatformOwnerLifecycleBody,
        actor: Annotated[PlatformActorContext, Depends(authenticated_actor)],
        _bearer: _NativeBearer,
        idempotency_key: _IdempotencyKey,
    ) -> PlatformOwnerLifecycleView:
        return await transition(
            principal_id,
            PlatformOwnerLifecycleAction.REACTIVATE,
            body,
            actor,
            idempotency_key,
        )

    async def revoke_owner(
        principal_id: UUID,
        body: PlatformOwnerLifecycleBody,
        actor: Annotated[PlatformActorContext, Depends(authenticated_actor)],
        _bearer: _NativeBearer,
        idempotency_key: _IdempotencyKey,
    ) -> PlatformOwnerLifecycleView:
        return await transition(
            principal_id,
            PlatformOwnerLifecycleAction.REVOKE,
            body,
            actor,
            idempotency_key,
        )

    mutation_responses = {status: {"model": ErrorEnvelope} for status in (400, 401, 403, 409, 422)}
    add_capability_route(
        router,
        "/v1/platform/owner-invitations",
        create_invitation,
        capability="platform.owner.provision",
        methods=["POST"],
        operation_id="platform_owner_invitation_create",
        owner="tenancy",
        status_code=201,
        response_model=PlatformOwnerInvitationView,
        responses=mutation_responses,
    )
    router.add_api_route(
        "/v1/platform/owner-invitations:enroll",
        enroll_invitation,
        methods=["POST"],
        operation_id="platform_owner_invitation_enroll",
        status_code=201,
        response_model=PlatformOwnerInvitationEnrollView,
        responses={status: {"model": ErrorEnvelope} for status in (401, 409, 422)},
    )
    add_capability_route(
        router,
        "/v1/platform/owner-invitations/{invitation_id}:activate",
        activate_invitation,
        capability="platform.owner.provision",
        methods=["POST"],
        operation_id="platform_owner_invitation_activate",
        owner="tenancy",
        status_code=201,
        response_model=PlatformOwnerProvisionView,
        responses=mutation_responses,
    )
    for action, endpoint in (
        ("suspend", suspend_owner),
        ("reactivate", reactivate_owner),
        ("revoke", revoke_owner),
    ):
        add_capability_route(
            router,
            f"/v1/platform/owners/{{principal_id}}:{action}",
            endpoint,
            capability="platform.owner.manage_lifecycle",
            methods=["POST"],
            operation_id=f"platform_owner_{action}",
            owner="tenancy",
            response_model=PlatformOwnerLifecycleView,
            responses=mutation_responses,
        )

    app.add_exception_handler(PlatformOwnerError, platform_owner_error_handler)
    app.include_router(router)
