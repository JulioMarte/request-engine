"""HTTP error mapping for the S0d identity-exchange surface."""

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from request_engine.modules.tenancy.application.identity_exchange_errors import (
    IdentityExchangeAlreadyAdopted,
    IdentityExchangeCandidateInvalid,
    IdentityExchangeError,
    IdentityExchangeOperatorRequired,
    IdentityExchangeProfileInvalid,
    IdentityExchangeUnavailable,
)
from request_engine.platform.http.errors import ErrorBody, ErrorEnvelope, ErrorResolution


class IdentityExchangeInputInvalid(Exception):
    """Transport input failed S0d application validation."""


def add_identity_exchange_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(IdentityExchangeInputInvalid, _input_error)
    app.add_exception_handler(IdentityExchangeError, _exchange_error)


async def _input_error(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, IdentityExchangeInputInvalid):
        raise exc
    return _response(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "identity_exchange_input_invalid",
        str(exc),
        ErrorResolution.FIX_REQUEST,
    )


async def _exchange_error(_: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, IdentityExchangeUnavailable):
        return _response(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "identity_exchange_unavailable",
            str(exc),
            ErrorResolution.OPERATOR_INTERVENTION,
        )
    if isinstance(exc, IdentityExchangeOperatorRequired):
        return _response(
            status.HTTP_403_FORBIDDEN,
            "identity_exchange_operator_required",
            str(exc),
            ErrorResolution.FIX_REQUEST,
        )
    if isinstance(exc, IdentityExchangeAlreadyAdopted):
        return _response(
            status.HTTP_409_CONFLICT,
            "identity_exchange_already_adopted",
            str(exc),
            ErrorResolution.CHOOSE_ALTERNATIVE,
            details={"existing_party_id": str(exc.existing_party_id)},
        )
    if isinstance(exc, IdentityExchangeCandidateInvalid):
        return _response(
            status.HTTP_409_CONFLICT,
            "identity_exchange_candidate_invalid",
            str(exc),
            ErrorResolution.REFRESH_AND_RETRY,
        )
    if isinstance(exc, IdentityExchangeProfileInvalid):
        return _response(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "identity_exchange_profile_invalid",
            str(exc),
            ErrorResolution.OPERATOR_INTERVENTION,
        )
    raise exc


def _response(
    status_code: int,
    code: str,
    message: str,
    resolution: ErrorResolution,
    *,
    details: dict[str, object] | None = None,
) -> JSONResponse:
    body = ErrorBody(
        code=code,
        message=message,
        resolution=resolution,
        details=details or {},
    )
    return JSONResponse(
        status_code=status_code,
        content=ErrorEnvelope(error=body).model_dump(mode="json"),
    )
