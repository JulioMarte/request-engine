"""HTTP error mapping for Party administrative identifiers."""

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from request_engine.modules.tenancy.application.administrative_identifier_errors import (
    PartyAdministrativeIdentifierConflict,
)
from request_engine.platform.http.errors import ErrorBody, ErrorEnvelope, ErrorResolution


def add_party_administrative_identifier_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(
        PartyAdministrativeIdentifierConflict,
        party_administrative_identifier_conflict_handler,
    )


async def party_administrative_identifier_conflict_handler(
    _: Request, exc: Exception
) -> JSONResponse:
    if not isinstance(exc, PartyAdministrativeIdentifierConflict):
        raise exc
    body = ErrorBody(
        code="party_administrative_identifier_conflict",
        message=str(exc),
        resolution=ErrorResolution.FIX_REQUEST,
        details={
            "kind": exc.kind,
            "issuer": exc.issuer,
            "normalized_value": exc.normalized_value,
            "existing_party_id": str(exc.existing_party_id),
        },
    )
    content = ErrorEnvelope(error=body).model_dump(mode="json")
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content=content)
