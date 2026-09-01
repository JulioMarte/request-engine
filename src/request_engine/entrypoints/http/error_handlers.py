"""Transport-global HTTP error handlers split out of errors.py for the line budget."""

from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from request_engine.platform.http.errors import ErrorBody, ErrorEnvelope, ErrorResolution


@runtime_checkable
class _HasSqlState(Protocol):
    sqlstate: str | None


def render_error_response(
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


_response = render_error_response


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
