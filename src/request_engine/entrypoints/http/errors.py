"""Transport-global HTTP error mapping for the process entrypoint."""

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from request_engine.entrypoints.http.error_handlers import (
    integrity_error_handler,
    render_error_response,
    request_validation_error_handler,
)
from request_engine.platform.http.errors import ErrorBody, ErrorResolution
from request_engine.platform.idempotency.errors import IdempotencyConflict
from request_engine.platform.security.acting_operator import OperatorResolutionUnavailable
from request_engine.platform.security.http import AuthenticationRequired, CapabilityRequired


def add_global_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AuthenticationRequired, authentication_required_handler)
    app.add_exception_handler(CapabilityRequired, capability_required_handler)
    app.add_exception_handler(
        OperatorResolutionUnavailable, operator_resolution_unavailable_handler
    )
    app.add_exception_handler(IdempotencyConflict, idempotency_conflict_handler)
    app.add_exception_handler(RequestValidationError, request_validation_error_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(IntegrityError, integrity_error_handler)


def _static_handler(
    status_code: int,
    code: str,
    message: str,
    resolution: ErrorResolution,
    *,
    retryable: bool = False,
) -> Callable[[Request, Exception], Awaitable[JSONResponse]]:
    async def handler(_: Request, exc: Exception) -> JSONResponse:
        return render_error_response(
            status_code,
            ErrorBody(code=code, message=message, resolution=resolution, retryable=retryable),
        )

    return handler


authentication_required_handler = _static_handler(
    status.HTTP_401_UNAUTHORIZED,
    "authentication_required",
    "authentication is required",
    ErrorResolution.REAUTHENTICATE,
)

operator_resolution_unavailable_handler = _static_handler(
    status.HTTP_503_SERVICE_UNAVAILABLE,
    "operator_resolution_unavailable",
    "the deployment does not provide acting-operator resolution",
    ErrorResolution.RETRY_SAME_REQUEST,
    retryable=True,
)


async def capability_required_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, CapabilityRequired):
        raise exc
    return render_error_response(
        status.HTTP_403_FORBIDDEN,
        ErrorBody(
            code="capability_required",
            message="the authenticated actor lacks a required capability",
            resolution=ErrorResolution.REQUEST_AUTHORITY,
            details={"capability": exc.capability},
        ),
    )


async def idempotency_conflict_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, IdempotencyConflict):
        raise exc
    return render_error_response(
        status.HTTP_409_CONFLICT,
        ErrorBody(
            code="idempotency_conflict",
            message="the idempotency key was already used for a different command",
            resolution=ErrorResolution.FIX_REQUEST,
            details={"capability": exc.capability, "idempotency_key": exc.idempotency_key},
        ),
    )


async def http_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, HTTPException):
        raise exc
    if exc.status_code == status.HTTP_404_NOT_FOUND:
        code = "not_found"
    elif exc.status_code == status.HTTP_405_METHOD_NOT_ALLOWED:
        code = "method_not_allowed"
    else:
        code = "http_error"
    return render_error_response(
        exc.status_code,
        ErrorBody(
            code=code,
            message=exc.detail,
            resolution=ErrorResolution.FIX_REQUEST,
            details={"status_code": exc.status_code},
        ),
        headers=exc.headers,
    )
