from fastapi import Request, status
from fastapi.responses import JSONResponse

from request_engine.platform.http.errors import ErrorBody, ErrorEnvelope, ErrorResolution
from request_engine.platform.public_contacts import PublicContactValidationError
from request_engine.platform.security.operational_authority import OperationalAuthorityRequired


def _response(status_code: int, body: ErrorBody) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=ErrorEnvelope(error=body).model_dump(mode="json"),
    )


async def operational_authority_required_handler(
    _: Request,
    exc: Exception,
) -> JSONResponse:
    if not isinstance(exc, OperationalAuthorityRequired):
        raise exc
    return _response(
        status.HTTP_403_FORBIDDEN,
        ErrorBody(
            code="operational_authority_required",
            message="the actor lacks operational authority for this Party",
            resolution=ErrorResolution.REQUEST_AUTHORITY,
            details={
                "authority_party_id": str(exc.authority_party_id),
                "scope_key": exc.scope_key,
            },
        ),
    )


async def public_contact_validation_error_handler(
    _: Request,
    exc: Exception,
) -> JSONResponse:
    if not isinstance(exc, PublicContactValidationError):
        raise exc
    return _response(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        ErrorBody(
            code="public_contact_invalid",
            message=str(exc),
            resolution=ErrorResolution.FIX_REQUEST,
        ),
    )
