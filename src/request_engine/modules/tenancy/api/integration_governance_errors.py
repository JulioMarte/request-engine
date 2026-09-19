from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from request_engine.modules.tenancy.application.errors import (
    IntegrationGovernanceConflict,
    IntegrationGovernanceError,
    IntegrationGovernanceForbidden,
    IntegrationGovernanceInputInvalid,
    IntegrationGovernanceNotFound,
    IntegrationGovernanceRevisionConflict,
)
from request_engine.platform.http.errors import ErrorBody, ErrorEnvelope, ErrorResolution


def add_integration_governance_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(IntegrationGovernanceError, integration_governance_error_handler)


async def integration_governance_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, IntegrationGovernanceError):
        raise exc
    status_code, body = _integration_governance_error(exc)
    return JSONResponse(
        status_code=status_code,
        content=ErrorEnvelope(error=body).model_dump(mode="json"),
    )


def _integration_governance_error(exc: IntegrationGovernanceError) -> tuple[int, ErrorBody]:
    if isinstance(exc, IntegrationGovernanceForbidden):
        return status.HTTP_403_FORBIDDEN, ErrorBody(
            code="integration_governance_forbidden",
            message="the current actor may not perform this integration governance operation",
            resolution=ErrorResolution.REQUEST_AUTHORITY,
        )
    if isinstance(exc, IntegrationGovernanceNotFound):
        return status.HTTP_404_NOT_FOUND, ErrorBody(
            code="integration_governance_not_found",
            message="integration Principal was not found in the current tenant",
            resolution=ErrorResolution.FIX_REQUEST,
        )
    if isinstance(exc, IntegrationGovernanceRevisionConflict):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="integration_governance_revision_conflict",
            message="integration state changed since the supplied revision",
            retryable=True,
            resolution=ErrorResolution.REFRESH_AND_RETRY,
        )
    if isinstance(exc, IntegrationGovernanceConflict):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="integration_governance_conflict",
            message="the requested integration governance change conflicts with current state",
            resolution=ErrorResolution.FIX_REQUEST,
        )
    if isinstance(exc, IntegrationGovernanceInputInvalid):
        return status.HTTP_422_UNPROCESSABLE_CONTENT, ErrorBody(
            code="integration_governance_input_invalid",
            message="the requested integration governance input is invalid",
            resolution=ErrorResolution.FIX_REQUEST,
        )
    return status.HTTP_500_INTERNAL_SERVER_ERROR, ErrorBody(
        code="integration_governance_error",
        message="the integration governance command failed",
        resolution=ErrorResolution.OPERATOR_INTERVENTION,
    )
