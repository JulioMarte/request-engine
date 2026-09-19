from collections.abc import Awaitable, Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Request, Response
from fastapi import status as http_status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from request_engine.modules.tenancy.api.party_registry_dependencies import IdempotencyKey
from request_engine.modules.tenancy.application.commands.controller_policy_upgrade import (
    CONTROLLER_POLICY_UPGRADE_CAPABILITY,
    ControllerPolicyUpgradeCommands,
    UpgradeControllerPolicyCommand,
)
from request_engine.modules.tenancy.application.errors import (
    ControllerPolicyUpgradeConflict,
    ControllerPolicyUpgradeError,
    ControllerPolicyUpgradeForbidden,
    ControllerPolicyUpgradeInputInvalid,
    ControllerPolicyUpgradeNotFound,
    ControllerPolicyUpgradeRevisionConflict,
)
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.http.errors import ErrorBody, ErrorEnvelope, ErrorResolution
from request_engine.platform.security.context import ActorContext, PrincipalKind
from request_engine.platform.security.http import require_capability


class ControllerPolicyUpgradeBody(BaseModel):
    target_principal_id: UUID
    source_policy_key: str = Field(min_length=1, max_length=200)
    target_policy_key: str = Field(min_length=1, max_length=200)
    expected_authority_revision: int = Field(ge=1)


class ControllerPolicyUpgradeView(BaseModel):
    authority_revision: int


def add_controller_policy_routes(
    router: APIRouter,
    *,
    commands: ControllerPolicyUpgradeCommands,
    authenticated_actor: Callable[[Request], Awaitable[ActorContext]],
) -> None:
    async def upgrade_controller_policy(
        body: ControllerPolicyUpgradeBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
        response: Response,
    ) -> ControllerPolicyUpgradeView:
        require_capability(actor, CONTROLLER_POLICY_UPGRADE_CAPABILITY)
        if actor.principal_kind is not PrincipalKind.HUMAN:
            raise ControllerPolicyUpgradeForbidden(
                "controller policy upgrade requires a HUMAN actor"
            )
        try:
            revision = await commands.upgrade_controller_policy(
                actor,
                UpgradeControllerPolicyCommand(
                    target_principal_id=body.target_principal_id,
                    source_policy_key=body.source_policy_key,
                    target_policy_key=body.target_policy_key,
                    expected_authority_revision=body.expected_authority_revision,
                    idempotency_key=idempotency_key,
                ),
            )
        except ValueError as exc:
            raise ControllerPolicyUpgradeInputInvalid(str(exc)) from None
        response.headers["Cache-Control"] = "no-store"
        return ControllerPolicyUpgradeView(authority_revision=revision)

    add_capability_route(
        router,
        "/v1/controller-policy-upgrades",
        upgrade_controller_policy,
        methods=["POST"],
        capability=CONTROLLER_POLICY_UPGRADE_CAPABILITY,
        operation_id="controller_policy_upgrade",
        owner="tenancy",
        response_model=ControllerPolicyUpgradeView,
    )


def add_controller_policy_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ControllerPolicyUpgradeError, controller_policy_error_handler)


async def controller_policy_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, ControllerPolicyUpgradeError):
        raise exc
    status_code, body = _controller_policy_error(exc)
    return JSONResponse(
        status_code=status_code,
        content=ErrorEnvelope(error=body).model_dump(mode="json"),
        headers={"Cache-Control": "no-store"},
    )


def _controller_policy_error(exc: ControllerPolicyUpgradeError) -> tuple[int, ErrorBody]:
    if isinstance(exc, ControllerPolicyUpgradeForbidden):
        return http_status.HTTP_403_FORBIDDEN, ErrorBody(
            code="controller_policy_upgrade_forbidden",
            message="the current actor may not perform this controller policy upgrade",
            resolution=ErrorResolution.REQUEST_AUTHORITY,
        )
    if isinstance(exc, ControllerPolicyUpgradeNotFound):
        return http_status.HTTP_404_NOT_FOUND, ErrorBody(
            code="controller_policy_upgrade_not_found",
            message="target Principal was not found in the current tenant",
            resolution=ErrorResolution.FIX_REQUEST,
        )
    if isinstance(exc, ControllerPolicyUpgradeRevisionConflict):
        return http_status.HTTP_409_CONFLICT, ErrorBody(
            code="controller_policy_upgrade_revision_conflict",
            message="controller authority changed since the supplied revision",
            retryable=True,
            resolution=ErrorResolution.REFRESH_AND_RETRY,
        )
    if isinstance(exc, ControllerPolicyUpgradeConflict):
        return http_status.HTTP_409_CONFLICT, ErrorBody(
            code="controller_policy_upgrade_conflict",
            message="the requested controller policy upgrade conflicts with current state",
            resolution=ErrorResolution.FIX_REQUEST,
        )
    if isinstance(exc, ControllerPolicyUpgradeInputInvalid):
        return http_status.HTTP_422_UNPROCESSABLE_CONTENT, ErrorBody(
            code="controller_policy_upgrade_invalid",
            message="the requested controller policy upgrade is invalid",
            resolution=ErrorResolution.FIX_REQUEST,
        )
    return http_status.HTTP_500_INTERNAL_SERVER_ERROR, ErrorBody(
        code="controller_policy_upgrade_error",
        message="the controller policy upgrade failed",
        resolution=ErrorResolution.OPERATOR_INTERVENTION,
    )
