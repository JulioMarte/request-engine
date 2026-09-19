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
    PlatformOwnerConflict,
    PlatformOwnerError,
    PlatformOwnerForbidden,
    PlatformOwnerInvalid,
    PlatformOwnerLifecycleAction,
    PlatformOwnerRevisionConflict,
    ProvisionPlatformOwnerCommand,
    TransitionPlatformOwnerCommand,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.http.errors import ErrorBody, ErrorEnvelope, ErrorResolution
from request_engine.platform.security.freshness import require_phishing_resistant_authentication
from request_engine.platform.security.platform_context import PlatformActorContext
from request_engine.platform.security.platform_http import PlatformActorResolver

_NativeBearer = Annotated[
    HTTPAuthorizationCredentials | None,
    Security(HTTPBearer(scheme_name="NativeSessionBearer", auto_error=False)),
]
_IdempotencyKey = Annotated[
    str, Header(alias="Idempotency-Key", min_length=1, max_length=200, pattern=r"\S")
]


class PlatformOwnerProvisionBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    native_identity_id: UUID
    provenance_reference: str = Field(min_length=1, max_length=500)


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

    async def create_owner(
        body: PlatformOwnerProvisionBody,
        actor: Annotated[PlatformActorContext, Depends(authenticated_actor)],
        _bearer: _NativeBearer,
        idempotency_key: _IdempotencyKey,
    ) -> PlatformOwnerProvisionView:
        require_phishing_resistant_authentication(actor, now=datetime.now(UTC))
        result = await commands.provision_owner(
            actor,
            ProvisionPlatformOwnerCommand(
                native_identity_id=body.native_identity_id,
                provenance_reference=body.provenance_reference,
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

    mutation_responses = {
        status: {"model": ErrorEnvelope}
        for status in (400, 401, 403, 409, 422)
    }
    add_capability_route(
        router,
        "/v1/platform/owners",
        create_owner,
        capability="platform.owner.provision",
        methods=["POST"],
        operation_id="platform_owner_create",
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
