"""HTTP error mapping for the tenancy party registry capabilities."""

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from request_engine.modules.tenancy.application.errors import (
    PartyContactPointExists,
    PartyContactPointNotFound,
    PartyDocumentConflict,
    PartyNotFound,
    PartyRegistryError,
)
from request_engine.platform.http.errors import ErrorBody, ErrorEnvelope, ErrorResolution


class PartyRegistryInputInvalid(Exception):
    """Raised at the transport edge when command input fails validation."""


def add_party_registry_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(PartyRegistryError, party_registry_error_handler)
    app.add_exception_handler(PartyRegistryInputInvalid, party_registry_input_error_handler)


async def party_registry_input_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, PartyRegistryInputInvalid):
        raise exc
    return _response(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        ErrorBody(
            code="party_registry_input_invalid",
            message=str(exc),
            resolution=ErrorResolution.FIX_REQUEST,
            details={"reason": str(exc)},
        ),
    )


async def party_registry_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, PartyRegistryError):
        raise exc
    status_code, body = _party_registry_error(exc)
    return _response(status_code, body)


def _party_registry_error(exc: PartyRegistryError) -> tuple[int, ErrorBody]:
    if isinstance(exc, PartyDocumentConflict):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="party_document_conflict",
            message=str(exc),
            resolution=ErrorResolution.FIX_REQUEST,
            details={"reason": exc.reason},
        )
    if isinstance(exc, PartyContactPointExists):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="party_contact_point_exists",
            message=str(exc),
            resolution=ErrorResolution.FIX_REQUEST,
            details={
                "party_id": str(exc.party_id),
                "channel": exc.channel,
                "normalized_value": exc.normalized_value,
            },
        )
    if isinstance(exc, PartyContactPointNotFound):
        return status.HTTP_404_NOT_FOUND, ErrorBody(
            code="party_contact_point_not_found",
            message=str(exc),
            resolution=ErrorResolution.FIX_REQUEST,
            details={
                "party_id": str(exc.party_id),
                "contact_point_id": str(exc.contact_point_id),
            },
        )
    if isinstance(exc, PartyNotFound):
        return status.HTTP_404_NOT_FOUND, ErrorBody(
            code="party_not_found",
            message=str(exc),
            resolution=ErrorResolution.FIX_REQUEST,
            details={"party_id": str(exc.party_id)},
        )
    return status.HTTP_500_INTERNAL_SERVER_ERROR, ErrorBody(
        code="party_registry_error",
        message="the party registry command failed",
        resolution=ErrorResolution.OPERATOR_INTERVENTION,
    )


def _response(status_code: int, body: ErrorBody) -> JSONResponse:
    content = ErrorEnvelope(error=body).model_dump(mode="json")
    return JSONResponse(status_code=status_code, content=content)
