"""Transport-global HTTP error mapping for the process entrypoint."""

from collections.abc import Awaitable, Callable, Mapping
from typing import Protocol, runtime_checkable

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from request_engine.platform.http.errors import ErrorBody, ErrorEnvelope, ErrorResolution
from request_engine.platform.idempotency.errors import IdempotencyConflict
from request_engine.platform.security.acting_operator import OperatorResolutionUnavailable
from request_engine.platform.security.http import AuthenticationRequired, CapabilityRequired


@runtime_checkable
class _HasSqlState(Protocol):
    sqlstate: str | None


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
        return _response(
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
    return _response(
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
    return _response(
        status.HTTP_409_CONFLICT,
        ErrorBody(
            code="idempotency_conflict",
            message="the idempotency key was already used for a different command",
            resolution=ErrorResolution.FIX_REQUEST,
            details={"capability": exc.capability, "idempotency_key": exc.idempotency_key},
        ),
    )


async def request_validation_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):
        raise exc
    fields = [
        {
            "location": list(error.get("loc", ())),
            "message": str(error.get("msg", "invalid value")),
            "type": str(error.get("type", "validation_error")),
        }
        for error in exc.errors()
    ]
    return _response(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        ErrorBody(
            code="validation_failed",
            message="the request did not satisfy the operation input contract",
            resolution=ErrorResolution.FIX_REQUEST,
            details={"fields": fields},
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
    return _response(
        exc.status_code,
        ErrorBody(
            code=code,
            message=exc.detail,
            resolution=ErrorResolution.FIX_REQUEST,
            details={"status_code": exc.status_code},
        ),
        headers=exc.headers,
    )


async def integrity_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, IntegrityError):
        raise exc
    sqlstate = exc.orig.sqlstate if isinstance(exc.orig, _HasSqlState) else None
    if sqlstate == "23505":
        return _response(
            status.HTTP_409_CONFLICT,
            ErrorBody(
                code="conflict",
                message="the command conflicts with existing authoritative state",
                resolution=ErrorResolution.REFRESH_AND_RETRY,
            ),
        )
    return _response(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        ErrorBody(
            code="database_integrity_error",
            message="the command violated an authoritative database invariant",
            resolution=ErrorResolution.OPERATOR_INTERVENTION,
        ),
    )


def _response(
    status_code: int,
    body: ErrorBody,
    *,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=ErrorEnvelope(error=body).model_dump(mode="json"),
        headers=headers,
    )
