"""Global error-handler registration for the process entrypoint."""

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from request_engine.entrypoints.http.errors import (
    authentication_required_handler,
    capability_required_handler,
    http_exception_handler,
    idempotency_conflict_handler,
    integrity_error_handler,
    render_error_response,
    request_validation_error_handler,
)
from request_engine.platform.http.errors import ErrorBody, ErrorResolution
from request_engine.platform.idempotency.errors import IdempotencyConflict
from request_engine.platform.security.acting_operator import OperatorResolutionUnavailable
from request_engine.platform.security.http import AuthenticationRequired, CapabilityRequired


async def operator_resolution_unavailable_handler(_: Request, exc: Exception) -> JSONResponse:
    return render_error_response(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        ErrorBody(
            code="operator_resolution_unavailable",
            message="the deployment does not provide acting-operator resolution",
            resolution=ErrorResolution.RETRY_SAME_REQUEST,
            retryable=True,
        ),
    )


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
