from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Header, Query, Request, Response, Security
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field

from request_engine.modules.tenancy.adapters.db.platform_provisioner_lifecycle_commands import (
    PostgresNativePlatformProvisionerLifecycleCommands,
)
from request_engine.modules.tenancy.adapters.db.platform_provisioner_reader import (
    PostgresPlatformProvisionerReader,
)
from request_engine.modules.tenancy.application.commands.platform_provisioner_lifecycle import (
    PlatformProvisionerLifecycleAction,
    PlatformProvisionerLifecycleConflict,
    PlatformProvisionerLifecycleError,
    PlatformProvisionerLifecycleForbidden,
    PlatformProvisionerLifecycleInvalid,
    PlatformProvisionerLifecycleNotFound,
    PlatformProvisionerLifecycleRevisionConflict,
    TransitionPlatformProvisionerCommand,
)
from request_engine.modules.tenancy.application.queries.platform_provisioner_read import (
    GetPlatformProvisionerQuery,
    ListPlatformProvisionersQuery,
    PlatformProvisionerNotFound,
    PlatformProvisionerReadError,
    PlatformProvisionerReadForbidden,
    PlatformProvisionerSummary,
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


class PlatformProvisionerLifecycleBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_revision: int = Field(ge=1)
    reason_code: str = Field(min_length=1, max_length=80)
    external_case_reference: str | None = Field(default=None, min_length=1, max_length=200)


class PlatformProvisionerView(BaseModel):
    principal_id: UUID
    principal_kind: str
    active: bool
    authority_revision: int
    binding_id: UUID | None
    binding_status: str | None
    identity_authority_id: UUID | None
    binding_subject_id: str | None
    capabilities: list[str]
    provenance_reference: str | None
    granted_at: datetime | None


class PlatformProvisionerPageView(BaseModel):
    items: list[PlatformProvisionerView]
    next_after: UUID | None


class PlatformProvisionerLifecycleView(BaseModel):
    fact_id: UUID
    principal_id: UUID
    action: str
    authority_revision: int
    binding_id: UUID | None
    binding_status: str | None


async def provisioner_management_error_handler(_: Request, exc: Exception) -> JSONResponse:
    errors: dict[type[Exception], tuple[int, str, ErrorResolution]] = {
        PlatformProvisionerReadForbidden: (
            403,
            "platform_provisioner_read_forbidden",
            ErrorResolution.REQUEST_AUTHORITY,
        ),
        PlatformProvisionerLifecycleForbidden: (
            403,
            "platform_provisioner_lifecycle_forbidden",
            ErrorResolution.REQUEST_AUTHORITY,
        ),
        PlatformProvisionerNotFound: (
            404,
            "platform_provisioner_not_found",
            ErrorResolution.FIX_REQUEST,
        ),
        PlatformProvisionerLifecycleNotFound: (
            404,
            "platform_provisioner_not_found",
            ErrorResolution.FIX_REQUEST,
        ),
        PlatformProvisionerLifecycleConflict: (
            409,
            "platform_provisioner_lifecycle_conflict",
            ErrorResolution.FIX_REQUEST,
        ),
        PlatformProvisionerLifecycleInvalid: (
            422,
            "platform_provisioner_lifecycle_invalid",
            ErrorResolution.FIX_REQUEST,
        ),
        PlatformProvisionerLifecycleRevisionConflict: (
            409,
            "platform_authority_changed",
            ErrorResolution.REFRESH_AND_RETRY,
        ),
    }
    status_code, code, resolution = errors.get(
        type(exc),
        (
            500,
            "platform_provisioner_management_failed",
            ErrorResolution.OPERATOR_INTERVENTION,
        ),
    )
    return JSONResponse(
        status_code=status_code,
        content=ErrorEnvelope(
            error=ErrorBody(
                code=code,
                message="The platform provisioner operation could not be accepted.",
                resolution=resolution,
                retryable=False,
            )
        ).model_dump(mode="json"),
        headers={"Cache-Control": "no-store"},
    )


def install_native_platform_provisioner_management_http(
    app: FastAPI,
    *,
    read_session_factory: SessionFactory,
    write_session_factory: SessionFactory,
    actor_resolver: PlatformActorResolver,
) -> None:
    reader = PostgresPlatformProvisionerReader(read_session_factory)
    commands = PostgresNativePlatformProvisionerLifecycleCommands(write_session_factory)
    router = APIRouter(tags=["Platform provisioning"])

    async def authenticated_actor(request: Request) -> PlatformActorContext:
        return await actor_resolver.resolve_platform_actor(request)

    async def list_provisioners(
        actor: Annotated[PlatformActorContext, Depends(authenticated_actor)],
        response: Response,
        _bearer: _NativeBearer,
        after: Annotated[UUID | None, Query()] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ) -> PlatformProvisionerPageView:
        rows = await reader.list_provisioners(
            actor, ListPlatformProvisionersQuery(after=after, limit=limit)
        )
        response.headers["Cache-Control"] = "no-store"
        return PlatformProvisionerPageView(
            items=[_view(row) for row in rows],
            next_after=rows[-1].principal_id if len(rows) == limit else None,
        )

    async def get_provisioner(
        principal_id: UUID,
        actor: Annotated[PlatformActorContext, Depends(authenticated_actor)],
        response: Response,
        _bearer: _NativeBearer,
    ) -> PlatformProvisionerView:
        row = await reader.get_provisioner(actor, GetPlatformProvisionerQuery(principal_id))
        if row is None:
            raise PlatformProvisionerNotFound("platform provisioner is not addressable")
        response.headers["Cache-Control"] = "no-store"
        return _view(row)

    async def transition(
        principal_id: UUID,
        action: PlatformProvisionerLifecycleAction,
        body: PlatformProvisionerLifecycleBody,
        actor: PlatformActorContext,
        idempotency_key: str,
    ) -> PlatformProvisionerLifecycleView:
        require_phishing_resistant_authentication(actor, now=datetime.now(UTC))
        result = await commands.transition_provisioner(
            actor,
            TransitionPlatformProvisionerCommand(
                principal_id=principal_id,
                action=action,
                expected_revision=body.expected_revision,
                reason_code=body.reason_code,
                idempotency_key=idempotency_key,
                external_case_reference=body.external_case_reference,
            ),
        )
        return PlatformProvisionerLifecycleView(
            fact_id=result.fact_id,
            principal_id=result.principal_id,
            action=result.action.value,
            authority_revision=result.authority_revision,
            binding_id=result.binding_id,
            binding_status=result.binding_status,
        )

    async def suspend_provisioner(
        principal_id: UUID,
        body: PlatformProvisionerLifecycleBody,
        actor: Annotated[PlatformActorContext, Depends(authenticated_actor)],
        _bearer: _NativeBearer,
        idempotency_key: _IdempotencyKey,
    ) -> PlatformProvisionerLifecycleView:
        return await transition(
            principal_id,
            PlatformProvisionerLifecycleAction.SUSPEND,
            body,
            actor,
            idempotency_key,
        )

    async def reactivate_provisioner(
        principal_id: UUID,
        body: PlatformProvisionerLifecycleBody,
        actor: Annotated[PlatformActorContext, Depends(authenticated_actor)],
        _bearer: _NativeBearer,
        idempotency_key: _IdempotencyKey,
    ) -> PlatformProvisionerLifecycleView:
        return await transition(
            principal_id,
            PlatformProvisionerLifecycleAction.REACTIVATE,
            body,
            actor,
            idempotency_key,
        )

    async def revoke_provisioner(
        principal_id: UUID,
        body: PlatformProvisionerLifecycleBody,
        actor: Annotated[PlatformActorContext, Depends(authenticated_actor)],
        _bearer: _NativeBearer,
        idempotency_key: _IdempotencyKey,
    ) -> PlatformProvisionerLifecycleView:
        return await transition(
            principal_id,
            PlatformProvisionerLifecycleAction.REVOKE,
            body,
            actor,
            idempotency_key,
        )

    error_responses = {status: {"model": ErrorEnvelope} for status in (400, 401, 403, 422)}
    lifecycle_responses = {
        status: {"model": ErrorEnvelope} for status in (400, 401, 403, 404, 409, 422)
    }
    add_capability_route(
        router,
        "/v1/platform/provisioners",
        list_provisioners,
        capability="platform.provisioner.read",
        methods=["GET"],
        operation_id="platform_native_provisioner_list",
        owner="tenancy",
        response_model=PlatformProvisionerPageView,
        responses=error_responses,
    )
    add_capability_route(
        router,
        "/v1/platform/provisioners/{principal_id}",
        get_provisioner,
        capability="platform.provisioner.read",
        methods=["GET"],
        operation_id="platform_native_provisioner_get",
        owner="tenancy",
        response_model=PlatformProvisionerView,
        responses={**error_responses, 404: {"model": ErrorEnvelope}},
    )
    for action, endpoint in (
        ("suspend", suspend_provisioner),
        ("reactivate", reactivate_provisioner),
        ("revoke", revoke_provisioner),
    ):
        add_capability_route(
            router,
            f"/v1/platform/provisioners/{{principal_id}}:{action}",
            endpoint,
            capability="platform.provisioner.manage_lifecycle",
            methods=["POST"],
            operation_id=f"platform_native_provisioner_{action}",
            owner="tenancy",
            response_model=PlatformProvisionerLifecycleView,
            responses=lifecycle_responses,
        )
    app.add_exception_handler(PlatformProvisionerReadError, provisioner_management_error_handler)
    app.add_exception_handler(
        PlatformProvisionerLifecycleError, provisioner_management_error_handler
    )
    app.include_router(router)


def _view(row: PlatformProvisionerSummary) -> PlatformProvisionerView:
    return PlatformProvisionerView(
        principal_id=row.principal_id,
        principal_kind=row.principal_kind,
        active=row.active,
        authority_revision=row.authority_revision,
        binding_id=row.binding_id,
        binding_status=row.binding_status,
        identity_authority_id=row.identity_authority_id,
        binding_subject_id=row.binding_subject_id,
        capabilities=list(row.capabilities),
        provenance_reference=row.provenance_reference,
        granted_at=row.granted_at,
    )
