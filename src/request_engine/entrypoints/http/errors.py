from typing import Protocol, runtime_checkable

from fastapi import Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from request_engine.platform.http.errors import ErrorBody, ErrorEnvelope


@runtime_checkable
class _HasSqlState(Protocol):
    sqlstate: str | None


async def integrity_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, IntegrityError):
        raise exc
    sqlstate = exc.orig.sqlstate if isinstance(exc.orig, _HasSqlState) else None
    if sqlstate == "23505":
        body = ErrorBody(
            code="conflict",
            message="the command conflicts with existing authoritative state",
        )
        return _response(status.HTTP_409_CONFLICT, body)
    body = ErrorBody(
        code="database_integrity_error",
        message="the command violated an authoritative database invariant",
    )
    return _response(status.HTTP_500_INTERNAL_SERVER_ERROR, body)


def _response(status_code: int, body: ErrorBody) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=ErrorEnvelope(error=body).model_dump())
