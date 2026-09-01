"""HTTP error mapping for the staff administrative contact capabilities.

The staff typed errors subclass `PartyRegistryError`; registering these
specific handlers beside the generic party registry handler maps them to
their own statuses instead of the generic 500 fallback (Starlette resolves
handlers along the exception MRO).
"""

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from request_engine.modules.tenancy.application.errors import (
    PrincipalContactExists,
    PrincipalContactNotFound,
    StaffContactForbidden,
    VerificationAttemptsExhausted,
    VerificationCodeExpired,
    VerificationCodeInvalid,
)
from request_engine.platform.http.errors import ErrorBody, ErrorEnvelope, ErrorResolution


def add_staff_contact_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(StaffContactForbidden, _staff_contact_forbidden_handler)
    app.add_exception_handler(PrincipalContactNotFound, _not_found_handler)
    app.add_exception_handler(PrincipalContactExists, _exists_handler)
    app.add_exception_handler(VerificationCodeInvalid, _code_invalid_handler)
    app.add_exception_handler(VerificationCodeExpired, _code_expired_handler)
    app.add_exception_handler(VerificationAttemptsExhausted, _attempts_exhausted_handler)


async def _staff_contact_forbidden_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StaffContactForbidden)
    return _response(
        status.HTTP_403_FORBIDDEN,
        ErrorBody(
            code="staff_contact_forbidden",
            message=str(exc),
            resolution=ErrorResolution.REQUEST_AUTHORITY,
            details={"principal_id": str(exc.principal_id)},
        ),
    )


async def _not_found_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, PrincipalContactNotFound)
    return _response(
        status.HTTP_404_NOT_FOUND,
        ErrorBody(
            code="principal_contact_not_found",
            message=str(exc),
            resolution=ErrorResolution.FIX_REQUEST,
            details={
                "principal_id": str(exc.principal_id),
                "contact_id": str(exc.contact_id),
            },
        ),
    )


async def _exists_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, PrincipalContactExists)
    return _response(
        status.HTTP_409_CONFLICT,
        ErrorBody(
            code="principal_contact_exists",
            message=str(exc),
            resolution=ErrorResolution.FIX_REQUEST,
            details={
                "principal_id": str(exc.principal_id),
                "channel": exc.channel,
                "normalized_value": exc.normalized_value,
            },
        ),
    )


async def _code_invalid_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, VerificationCodeInvalid)
    return _response(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        ErrorBody(
            code="verification_code_invalid",
            message=str(exc),
            resolution=ErrorResolution.FIX_REQUEST,
            details={"attempts_remaining": exc.attempts_remaining},
        ),
    )


async def _code_expired_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, VerificationCodeExpired)
    return _response(
        status.HTTP_410_GONE,
        ErrorBody(
            code="verification_code_expired",
            message=str(exc),
            resolution=ErrorResolution.FIX_REQUEST,
        ),
    )


async def _attempts_exhausted_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, VerificationAttemptsExhausted)
    return _response(
        status.HTTP_429_TOO_MANY_REQUESTS,
        ErrorBody(
            code="verification_attempts_exhausted",
            message=str(exc),
            resolution=ErrorResolution.CHOOSE_ALTERNATIVE,
        ),
    )


def _response(status_code: int, body: ErrorBody) -> JSONResponse:
    content = ErrorEnvelope(error=body).model_dump(mode="json")
    return JSONResponse(status_code=status_code, content=content)
