"""HTTP error mapping for the staff administrative contact capabilities.

The staff typed errors subclass `PartyRegistryError`; registering these
specific handlers beside the generic party registry handler maps them to
their own statuses instead of the generic 500 fallback (Starlette resolves
handlers along the exception MRO).
"""

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from request_engine.modules.tenancy.application.errors import (
    PrincipalContactExists,
    PrincipalContactNotFound,
    StaffContactForbidden,
    VerificationAlreadyPending,
    VerificationAttemptsExhausted,
    VerificationCodeExpired,
    VerificationCodeInvalid,
)
from request_engine.platform.http.errors import ErrorBody, ErrorEnvelope, ErrorResolution


def _forbidden_details(exc: StaffContactForbidden) -> dict[str, object]:
    return {"principal_id": str(exc.principal_id)}


def _not_found_details(exc: PrincipalContactNotFound) -> dict[str, object]:
    return {"principal_id": str(exc.principal_id), "contact_id": str(exc.contact_id)}


def _exists_details(exc: PrincipalContactExists) -> dict[str, object]:
    return {
        "principal_id": str(exc.principal_id),
        "channel": exc.channel,
        "normalized_value": exc.normalized_value,
    }


def _code_invalid_details(exc: VerificationCodeInvalid) -> dict[str, object]:
    return {"attempts_remaining": exc.attempts_remaining}


def _already_pending_details(exc: VerificationAlreadyPending) -> dict[str, object]:
    return {"expires_at": exc.expires_at.isoformat()}


_STAFF_CONTACT_ERRORS: tuple[
    tuple[type[Exception], int, str, ErrorResolution, Callable[[Any], dict[str, object]]],
    ...,
] = (
    (
        StaffContactForbidden,
        status.HTTP_403_FORBIDDEN,
        "staff_contact_forbidden",
        ErrorResolution.REQUEST_AUTHORITY,
        _forbidden_details,
    ),
    (
        PrincipalContactNotFound,
        status.HTTP_404_NOT_FOUND,
        "principal_contact_not_found",
        ErrorResolution.FIX_REQUEST,
        _not_found_details,
    ),
    (
        PrincipalContactExists,
        status.HTTP_409_CONFLICT,
        "principal_contact_exists",
        ErrorResolution.FIX_REQUEST,
        _exists_details,
    ),
    (
        VerificationCodeInvalid,
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "verification_code_invalid",
        ErrorResolution.FIX_REQUEST,
        _code_invalid_details,
    ),
    (
        VerificationAlreadyPending,
        status.HTTP_409_CONFLICT,
        "verification_already_pending",
        ErrorResolution.REFRESH_AND_RETRY,
        _already_pending_details,
    ),
    (
        VerificationCodeExpired,
        status.HTTP_410_GONE,
        "verification_code_expired",
        ErrorResolution.FIX_REQUEST,
        lambda _exc: {},
    ),
    (
        VerificationAttemptsExhausted,
        status.HTTP_429_TOO_MANY_REQUESTS,
        "verification_attempts_exhausted",
        ErrorResolution.CHOOSE_ALTERNATIVE,
        lambda _exc: {},
    ),
)


def add_staff_contact_error_handlers(app: FastAPI) -> None:
    for error_type, status_code, code, resolution, details in _STAFF_CONTACT_ERRORS:
        app.add_exception_handler(
            error_type,
            _staff_contact_handler(status_code, code, resolution, details),
        )


def _staff_contact_handler(
    status_code: int,
    code: str,
    resolution: ErrorResolution,
    details: Callable[[Any], dict[str, object]],
) -> Callable[[Request, Exception], Awaitable[JSONResponse]]:
    async def handler(_: Request, exc: Exception) -> JSONResponse:
        return _response(
            status_code,
            ErrorBody(code=code, message=str(exc), resolution=resolution, details=details(exc)),
        )

    return handler


def _response(status_code: int, body: ErrorBody) -> JSONResponse:
    content = ErrorEnvelope(error=body).model_dump(mode="json")
    return JSONResponse(status_code=status_code, content=content)
