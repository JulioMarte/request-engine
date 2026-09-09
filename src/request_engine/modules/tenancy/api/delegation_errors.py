from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from request_engine.modules.tenancy.application.errors import (
    DelegationConflict,
    DelegationError,
    DelegationForbidden,
    DelegationInputInvalid,
    DelegationNotFound,
    DelegationRevisionConflict,
)
from request_engine.platform.http.errors import ErrorBody, ErrorEnvelope, ErrorResolution


def add_delegation_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DelegationError, delegation_error_handler)


async def delegation_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, DelegationError):
        raise exc
    status_code, body = _delegation_error(exc)
    return JSONResponse(
        status_code=status_code,
        content=ErrorEnvelope(error=body).model_dump(mode="json"),
    )


def _delegation_error(exc: DelegationError) -> tuple[int, ErrorBody]:
    if isinstance(exc, DelegationForbidden):
        return status.HTTP_403_FORBIDDEN, ErrorBody(
            code="delegation_forbidden",
            message="the current actor may not perform this delegation operation",
            resolution=ErrorResolution.REQUEST_AUTHORITY,
        )
    if isinstance(exc, DelegationNotFound):
        return status.HTTP_404_NOT_FOUND, ErrorBody(
            code="delegation_not_found",
            message="delegation was not found in the current tenant",
            resolution=ErrorResolution.FIX_REQUEST,
        )
    if isinstance(exc, DelegationRevisionConflict):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="delegation_revision_conflict",
            message="delegation state changed since the supplied revision",
            retryable=True,
            resolution=ErrorResolution.REFRESH_AND_RETRY,
        )
    if isinstance(exc, DelegationConflict):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="delegation_conflict",
            message="the requested delegation change conflicts with current state",
            resolution=ErrorResolution.FIX_REQUEST,
        )
    if isinstance(exc, DelegationInputInvalid):
        return status.HTTP_422_UNPROCESSABLE_CONTENT, ErrorBody(
            code="delegation_input_invalid",
            message="the requested delegation input is invalid",
            resolution=ErrorResolution.FIX_REQUEST,
        )
    return status.HTTP_500_INTERNAL_SERVER_ERROR, ErrorBody(
        code="delegation_error",
        message="the delegation command failed",
        resolution=ErrorResolution.OPERATOR_INTERVENTION,
    )
