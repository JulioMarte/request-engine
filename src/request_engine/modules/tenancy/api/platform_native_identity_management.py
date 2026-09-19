from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Header, Request
from fastapi import status as http_status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from request_engine.modules.tenancy.adapters.db.native_identity_disable_commands import (
    PostgresNativeIdentityDisableCommands,
)
from request_engine.modules.tenancy.adapters.db.native_identity_reader import (
    PostgresNativeIdentityReader,
)
from request_engine.modules.tenancy.application.commands.native_identity_disable import (
    NATIVE_IDENTITY_DISABLE_CAPABILITY,
    DisableNativeIdentityCommand,
    NativeIdentityDisableConflict,
    NativeIdentityDisableError,
    NativeIdentityDisableForbidden,
    NativeIdentityDisableInvalid,
    NativeIdentityDisableNotFound,
    NativeIdentityDisableRevisionConflict,
)
from request_engine.modules.tenancy.application.queries.native_identity_read import (
    NATIVE_IDENTITY_READ_CAPABILITY,
    GetNativeIdentityQuery,
    ListNativeIdentitiesQuery,
    NativeIdentityReadError,
    NativeIdentityReadForbidden,
    NativeIdentityReadInvalid,
    NativeIdentityReadNotFound,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.http.errors import ErrorBody, ErrorEnvelope, ErrorResolution
from request_engine.platform.security.platform_context import PlatformActorContext
from request_engine.platform.security.platform_http import PlatformActorResolver

PlatformIdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=1, max_length=250),
]


class NativeIdentityView(BaseModel):
    native_identity_id: UUID
    identity_authority_id: UUID
    status: str
    revision: int
    created_at: datetime
    disabled_at: datetime | None


class NativeIdentityPageView(BaseModel):
    items: list[NativeIdentityView]
    next_cursor: UUID | None


class NativeIdentityListParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    after: UUID | None = None
    limit: int = Field(default=50, ge=1, le=100)


class NativeIdentityDisableBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    reason_code: str = Field(min_length=1, max_length=80)
    external_case_reference: str | None = Field(default=None, max_length=200)


class NativeIdentityDisableView(BaseModel):
    fact_id: UUID
    native_identity_id: UUID
    revision_after: int
    affected_tenant_count: int
    affected_platform: bool


def _view(identity: object) -> NativeIdentityView:
    return NativeIdentityView(
        native_identity_id=identity.native_identity_id,  # type: ignore[attr-defined]
        identity_authority_id=identity.identity_authority_id,  # type: ignore[attr-defined]
        status=identity.status,  # type: ignore[attr-defined]
        revision=identity.revision,  # type: ignore[attr-defined]
        created_at=identity.created_at,  # type: ignore[attr-defined]
        disabled_at=identity.disabled_at,  # type: ignore[attr-defined]
    )


def install_native_identity_management_http(
    app: FastAPI,
    *,
    read_session_factory: SessionFactory,
    write_session_factory: SessionFactory,
    actor_resolver: PlatformActorResolver,
) -> None:
    reader = PostgresNativeIdentityReader(read_session_factory)
    commands = PostgresNativeIdentityDisableCommands(write_session_factory)
    router = APIRouter(tags=["platform native identities"])

    async def authenticated_actor(request: Request) -> PlatformActorContext:
        return await actor_resolver.resolve_platform_actor(request)

    async def list_identities(
        params: Annotated[NativeIdentityListParams, Depends()],
        actor: Annotated[PlatformActorContext, Depends(authenticated_actor)],
    ) -> NativeIdentityPageView:
        rows = await reader.list_identities(
            actor, ListNativeIdentitiesQuery(after=params.after, limit=params.limit)
        )
        return NativeIdentityPageView(
            items=[_view(row) for row in rows],
            next_cursor=rows[-1].native_identity_id if len(rows) == params.limit else None,
        )

    async def read_identity(
        native_identity_id: UUID,
        actor: Annotated[PlatformActorContext, Depends(authenticated_actor)],
    ) -> NativeIdentityView:
        return _view(await reader.read_identity(actor, GetNativeIdentityQuery(native_identity_id)))

    async def disable_identity(
        native_identity_id: UUID,
        body: NativeIdentityDisableBody,
        actor: Annotated[PlatformActorContext, Depends(authenticated_actor)],
        idempotency_key: PlatformIdempotencyKey,
    ) -> NativeIdentityDisableView:
        result = await commands.disable_identity(
            actor,
            DisableNativeIdentityCommand(
                native_identity_id=native_identity_id,
                expected_revision=body.expected_revision,
                reason_code=body.reason_code,
                external_case_reference=body.external_case_reference,
                idempotency_key=idempotency_key,
            ),
        )
        return NativeIdentityDisableView(
            fact_id=result.fact_id,
            native_identity_id=result.native_identity_id,
            revision_after=result.revision_after,
            affected_tenant_count=result.affected_tenant_count,
            affected_platform=result.affected_platform,
        )

    read_responses = {status: {"model": ErrorEnvelope} for status in (401, 403, 422)}
    case_responses = {**read_responses, 404: {"model": ErrorEnvelope}}
    mutation_responses = {**case_responses, 409: {"model": ErrorEnvelope}}
    add_capability_route(
        router,
        "/v1/platform/native-identities",
        list_identities,
        capability=NATIVE_IDENTITY_READ_CAPABILITY,
        methods=["GET"],
        operation_id="platform_native_identity_list",
        owner="tenancy",
        response_model=NativeIdentityPageView,
        responses=read_responses,
    )
    add_capability_route(
        router,
        "/v1/platform/native-identities/{native_identity_id}",
        read_identity,
        capability=NATIVE_IDENTITY_READ_CAPABILITY,
        methods=["GET"],
        operation_id="platform_native_identity_get",
        owner="tenancy",
        response_model=NativeIdentityView,
        responses=case_responses,
    )
    add_capability_route(
        router,
        "/v1/platform/native-identities/{native_identity_id}:disable",
        disable_identity,
        capability=NATIVE_IDENTITY_DISABLE_CAPABILITY,
        methods=["POST"],
        operation_id="platform_native_identity_disable",
        owner="tenancy",
        response_model=NativeIdentityDisableView,
        responses=mutation_responses,
    )
    app.add_exception_handler(NativeIdentityReadError, native_identity_error_handler)
    app.add_exception_handler(NativeIdentityDisableError, native_identity_error_handler)
    app.include_router(router)


async def native_identity_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, NativeIdentityReadError):
        status_code, body = _read_error(exc)
    elif isinstance(exc, NativeIdentityDisableError):
        status_code, body = _disable_error(exc)
    else:
        raise exc
    return JSONResponse(
        status_code=status_code,
        content=ErrorEnvelope(error=body).model_dump(mode="json"),
        headers={"Cache-Control": "no-store"},
    )


def _read_error(exc: NativeIdentityReadError) -> tuple[int, ErrorBody]:
    if isinstance(exc, NativeIdentityReadForbidden):
        return http_status.HTTP_403_FORBIDDEN, ErrorBody(
            code="native_identity_forbidden",
            message="the current operator may not inspect native identities",
            resolution=ErrorResolution.REQUEST_AUTHORITY,
        )
    if isinstance(exc, NativeIdentityReadNotFound):
        return http_status.HTTP_404_NOT_FOUND, ErrorBody(
            code="native_identity_not_found",
            message="native identity was not found",
            resolution=ErrorResolution.FIX_REQUEST,
        )
    if isinstance(exc, NativeIdentityReadInvalid):
        return http_status.HTTP_422_UNPROCESSABLE_CONTENT, ErrorBody(
            code="native_identity_invalid",
            message="the native identity query is invalid",
            resolution=ErrorResolution.FIX_REQUEST,
        )
    return http_status.HTTP_500_INTERNAL_SERVER_ERROR, ErrorBody(
        code="native_identity_error",
        message="the native identity read failed",
        resolution=ErrorResolution.OPERATOR_INTERVENTION,
    )


def _disable_error(exc: NativeIdentityDisableError) -> tuple[int, ErrorBody]:
    if isinstance(exc, NativeIdentityDisableForbidden):
        return http_status.HTTP_403_FORBIDDEN, ErrorBody(
            code="native_identity_disable_forbidden",
            message="the current operator may not disable native identities",
            resolution=ErrorResolution.REQUEST_AUTHORITY,
        )
    if isinstance(exc, NativeIdentityDisableNotFound):
        return http_status.HTTP_404_NOT_FOUND, ErrorBody(
            code="native_identity_not_found",
            message="native identity was not found",
            resolution=ErrorResolution.FIX_REQUEST,
        )
    if isinstance(exc, NativeIdentityDisableRevisionConflict):
        return http_status.HTTP_409_CONFLICT, ErrorBody(
            code="native_identity_disable_revision_conflict",
            message="native identity state changed since the supplied revision",
            retryable=True,
            resolution=ErrorResolution.REFRESH_AND_RETRY,
        )
    if isinstance(exc, NativeIdentityDisableConflict):
        return http_status.HTTP_409_CONFLICT, ErrorBody(
            code="native_identity_disable_conflict",
            message="native identity cannot be disabled in its current state",
            resolution=ErrorResolution.FIX_REQUEST,
        )
    if isinstance(exc, NativeIdentityDisableInvalid):
        return http_status.HTTP_422_UNPROCESSABLE_CONTENT, ErrorBody(
            code="native_identity_disable_invalid",
            message="the native identity disable request is invalid",
            resolution=ErrorResolution.FIX_REQUEST,
        )
    return http_status.HTTP_500_INTERNAL_SERVER_ERROR, ErrorBody(
        code="native_identity_disable_error",
        message="the native identity disable failed",
        resolution=ErrorResolution.OPERATOR_INTERVENTION,
    )
