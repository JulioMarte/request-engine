from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Query, Request, Response
from fastapi import status as http_status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from request_engine.modules.tenancy.api.party_registry_dependencies import IdempotencyKey
from request_engine.modules.tenancy.application.commands.identity_binding import (
    IDENTITY_BINDING_CAPABILITY,
    IdentityBindingCommands,
    IdentityBindingTargetStatus,
    TransitionIdentityBindingCommand,
)
from request_engine.modules.tenancy.application.errors import (
    IdentityBindingLifecycleConflict,
    IdentityBindingLifecycleError,
    IdentityBindingLifecycleForbidden,
    IdentityBindingLifecycleInputInvalid,
    IdentityBindingLifecycleNotFound,
    IdentityBindingLifecycleRevisionConflict,
)
from request_engine.modules.tenancy.application.queries.identity_binding import (
    IDENTITY_BINDING_READ_CAPABILITY,
    GetIdentityBindingQuery,
    IdentityBindingNotFound,
    IdentityBindingReader,
    IdentityBindingReadError,
    IdentityBindingReadForbidden,
    IdentityBindingReadInvalid,
    ListIdentityBindingsQuery,
)
from request_engine.modules.tenancy.application.queries.identity_binding import (
    IdentityBindingView as IdentityBindingSummary,
)
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.http.errors import ErrorBody, ErrorEnvelope, ErrorResolution
from request_engine.platform.security.context import ActorContext, PrincipalKind
from request_engine.platform.security.http import require_capability


class IdentityBindingView(BaseModel):
    binding_id: UUID
    principal_id: UUID
    identity_authority_id: UUID
    status: str
    revision: int
    created_at: datetime


class IdentityBindingPageView(BaseModel):
    items: list[IdentityBindingView]
    next_cursor: UUID | None


class IdentityBindingListParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    principal_id: UUID | None = None
    status: str | None = Field(default=None, max_length=32)
    after: UUID | None = None
    limit: int = Field(default=50, ge=1, le=100)


class IdentityBindingTransitionBody(BaseModel):
    expected_revision: int = Field(ge=1)
    provenance_reference: str = Field(min_length=1, max_length=500)


class IdentityBindingTransitionView(BaseModel):
    binding_revision: int


def _view(binding: IdentityBindingSummary) -> IdentityBindingView:
    return IdentityBindingView(
        binding_id=binding.binding_id,
        principal_id=binding.principal_id,
        identity_authority_id=binding.identity_authority_id,
        status=binding.status,
        revision=binding.revision,
        created_at=binding.created_at,
    )


def add_identity_binding_routes(
    router: APIRouter,
    *,
    reader: IdentityBindingReader,
    commands: IdentityBindingCommands,
    authenticated_actor: Callable[[Request], Awaitable[ActorContext]],
) -> None:
    async def list_bindings(
        params: Annotated[IdentityBindingListParams, Query()],
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        response: Response,
    ) -> IdentityBindingPageView:
        require_capability(actor, IDENTITY_BINDING_READ_CAPABILITY)
        response.headers["Cache-Control"] = "no-store"
        try:
            rows = await reader.list_bindings(
                actor,
                ListIdentityBindingsQuery(
                    principal_id=params.principal_id,
                    status=params.status,
                    after=params.after,
                    limit=params.limit,
                ),
            )
        except ValueError as exc:
            raise IdentityBindingReadInvalid(str(exc)) from None
        return IdentityBindingPageView(
            items=[_view(row) for row in rows],
            next_cursor=rows[-1].binding_id if len(rows) == params.limit else None,
        )

    async def read_binding(
        binding_id: UUID,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        response: Response,
    ) -> IdentityBindingView:
        require_capability(actor, IDENTITY_BINDING_READ_CAPABILITY)
        response.headers["Cache-Control"] = "no-store"
        return _view(await reader.read_binding(actor, GetIdentityBindingQuery(binding_id)))

    add_capability_route(
        router,
        "/v1/identity-bindings",
        list_bindings,
        methods=["GET"],
        capability=IDENTITY_BINDING_READ_CAPABILITY,
        operation_id="identity_binding_list",
        owner="tenancy",
        response_model=IdentityBindingPageView,
    )
    add_capability_route(
        router,
        "/v1/identity-bindings/{binding_id}",
        read_binding,
        methods=["GET"],
        capability=IDENTITY_BINDING_READ_CAPABILITY,
        operation_id="identity_binding_get",
        owner="tenancy",
        response_model=IdentityBindingView,
    )

    async def _transition(
        actor: ActorContext,
        binding_id: UUID,
        body: IdentityBindingTransitionBody,
        target_status: IdentityBindingTargetStatus,
        idempotency_key: str,
        response: Response,
    ) -> IdentityBindingTransitionView:
        require_capability(actor, IDENTITY_BINDING_CAPABILITY)
        if actor.principal_kind is not PrincipalKind.HUMAN:
            raise IdentityBindingLifecycleForbidden(
                "identity binding commands require a HUMAN actor"
            )
        try:
            revision = await commands.transition_identity_binding(
                actor,
                TransitionIdentityBindingCommand(
                    binding_id=binding_id,
                    expected_revision=body.expected_revision,
                    target_status=target_status,
                    provenance_reference=body.provenance_reference,
                    idempotency_key=idempotency_key,
                ),
            )
        except ValueError as exc:
            raise IdentityBindingLifecycleInputInvalid(str(exc)) from None
        response.headers["Cache-Control"] = "no-store"
        return IdentityBindingTransitionView(binding_revision=revision)

    async def suspend_binding(
        binding_id: UUID,
        body: IdentityBindingTransitionBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
        response: Response,
    ) -> IdentityBindingTransitionView:
        return await _transition(
            actor,
            binding_id,
            body,
            IdentityBindingTargetStatus.SUSPENDED,
            idempotency_key,
            response,
        )

    async def reactivate_binding(
        binding_id: UUID,
        body: IdentityBindingTransitionBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
        response: Response,
    ) -> IdentityBindingTransitionView:
        return await _transition(
            actor,
            binding_id,
            body,
            IdentityBindingTargetStatus.ACTIVE,
            idempotency_key,
            response,
        )

    async def revoke_binding(
        binding_id: UUID,
        body: IdentityBindingTransitionBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
        response: Response,
    ) -> IdentityBindingTransitionView:
        return await _transition(
            actor,
            binding_id,
            body,
            IdentityBindingTargetStatus.REVOKED,
            idempotency_key,
            response,
        )

    add_capability_route(
        router,
        "/v1/identity-bindings/{binding_id}:suspend",
        suspend_binding,
        methods=["POST"],
        capability=IDENTITY_BINDING_CAPABILITY,
        operation_id="identity_binding_suspend",
        owner="tenancy",
        response_model=IdentityBindingTransitionView,
    )
    add_capability_route(
        router,
        "/v1/identity-bindings/{binding_id}:reactivate",
        reactivate_binding,
        methods=["POST"],
        capability=IDENTITY_BINDING_CAPABILITY,
        operation_id="identity_binding_reactivate",
        owner="tenancy",
        response_model=IdentityBindingTransitionView,
    )
    add_capability_route(
        router,
        "/v1/identity-bindings/{binding_id}:revoke",
        revoke_binding,
        methods=["POST"],
        capability=IDENTITY_BINDING_CAPABILITY,
        operation_id="identity_binding_revoke",
        owner="tenancy",
        response_model=IdentityBindingTransitionView,
    )


def add_identity_binding_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(IdentityBindingReadError, identity_binding_error_handler)
    app.add_exception_handler(
        IdentityBindingLifecycleError, identity_binding_lifecycle_error_handler
    )


async def identity_binding_lifecycle_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, IdentityBindingLifecycleError):
        raise exc
    status_code, body = _identity_binding_lifecycle_error(exc)
    return JSONResponse(
        status_code=status_code,
        content=ErrorEnvelope(error=body).model_dump(mode="json"),
        headers={"Cache-Control": "no-store"},
    )


def _identity_binding_lifecycle_error(
    exc: IdentityBindingLifecycleError,
) -> tuple[int, ErrorBody]:
    if isinstance(exc, IdentityBindingLifecycleForbidden):
        return http_status.HTTP_403_FORBIDDEN, ErrorBody(
            code="identity_binding_forbidden",
            message="the current actor may not manage identity bindings",
            resolution=ErrorResolution.REQUEST_AUTHORITY,
        )
    if isinstance(exc, IdentityBindingLifecycleNotFound):
        return http_status.HTTP_404_NOT_FOUND, ErrorBody(
            code="identity_binding_not_found",
            message="identity binding was not found in the current tenant",
            resolution=ErrorResolution.FIX_REQUEST,
        )
    if isinstance(exc, IdentityBindingLifecycleRevisionConflict):
        return http_status.HTTP_409_CONFLICT, ErrorBody(
            code="identity_binding_revision_conflict",
            message="identity binding state changed since the supplied revision",
            retryable=True,
            resolution=ErrorResolution.REFRESH_AND_RETRY,
        )
    if isinstance(exc, IdentityBindingLifecycleConflict):
        return http_status.HTTP_409_CONFLICT, ErrorBody(
            code="identity_binding_conflict",
            message="identity binding state conflicts with this request",
            resolution=ErrorResolution.FIX_REQUEST,
        )
    if isinstance(exc, IdentityBindingLifecycleInputInvalid):
        return http_status.HTTP_422_UNPROCESSABLE_CONTENT, ErrorBody(
            code="identity_binding_invalid",
            message="the identity binding transition is invalid",
            resolution=ErrorResolution.FIX_REQUEST,
        )
    return http_status.HTTP_500_INTERNAL_SERVER_ERROR, ErrorBody(
        code="identity_binding_error",
        message="the identity binding transition failed",
        resolution=ErrorResolution.OPERATOR_INTERVENTION,
    )


async def identity_binding_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, IdentityBindingReadError):
        raise exc
    status_code, body = _identity_binding_error(exc)
    return JSONResponse(
        status_code=status_code,
        content=ErrorEnvelope(error=body).model_dump(mode="json"),
        headers={"Cache-Control": "no-store"},
    )


def _identity_binding_error(exc: IdentityBindingReadError) -> tuple[int, ErrorBody]:
    if isinstance(exc, IdentityBindingReadForbidden):
        return http_status.HTTP_403_FORBIDDEN, ErrorBody(
            code="identity_binding_forbidden",
            message="the current actor may not inspect identity bindings",
            resolution=ErrorResolution.REQUEST_AUTHORITY,
        )
    if isinstance(exc, IdentityBindingNotFound):
        return http_status.HTTP_404_NOT_FOUND, ErrorBody(
            code="identity_binding_not_found",
            message="identity binding was not found in the current tenant",
            resolution=ErrorResolution.FIX_REQUEST,
        )
    if isinstance(exc, IdentityBindingReadInvalid):
        return http_status.HTTP_422_UNPROCESSABLE_CONTENT, ErrorBody(
            code="identity_binding_invalid",
            message="the identity binding query is invalid",
            resolution=ErrorResolution.FIX_REQUEST,
        )
    return http_status.HTTP_500_INTERNAL_SERVER_ERROR, ErrorBody(
        code="identity_binding_error",
        message="the identity binding read failed",
        resolution=ErrorResolution.OPERATOR_INTERVENTION,
    )
