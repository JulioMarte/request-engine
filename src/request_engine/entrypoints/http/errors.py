from typing import Protocol, runtime_checkable

from fastapi import HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from request_engine.platform.http.errors import ErrorBody, ErrorEnvelope, ErrorResolution
from request_engine.platform.security.http import AuthenticationRequired, CapabilityRequired


@runtime_checkable
class _HasSqlState(Protocol):
    sqlstate: str | None


async def authentication_required_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, AuthenticationRequired):
        raise exc
    return _response(
        status.HTTP_401_UNAUTHORIZED,
        ErrorBody(
            code="authentication_required",
            message="authentication is required",
            resolution=ErrorResolution.REAUTHENTICATE,
        ),
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


async def request_validation_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):
        raise exc
    fields: list[dict[str, object]] = []
    for error in exc.errors():
        fields.append(
            {
                "location": list(error.get("loc", ())),
                "message": str(error.get("msg", "invalid value")),
                "type": str(error.get("type", "validation_error")),
            }
        )
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
    message = exc.detail if isinstance(exc.detail, str) else "the request could not be processed"
    return _response(
        exc.status_code,
        ErrorBody(
            code=code,
            message=message,
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
        body = ErrorBody(
            code="conflict",
            message="the command conflicts with existing authoritative state",
            resolution=ErrorResolution.REFRESH_AND_RETRY,
        )
        return _response(status.HTTP_409_CONFLICT, body)
    body = ErrorBody(
        code="database_integrity_error",
        message="the command violated an authoritative database invariant",
        resolution=ErrorResolution.OPERATOR_INTERVENTION,
    )
    return _response(status.HTTP_500_INTERNAL_SERVER_ERROR, body)


def _response(
    status_code: int,
    body: ErrorBody,
    *,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=ErrorEnvelope(error=body).model_dump(mode="json"),
        headers=headers,
    )
