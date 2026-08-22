from fastapi import Request, status
from fastapi.responses import JSONResponse

from request_engine.modules.discovery.application.errors import (
    DiscoveryConfigurationConflict,
    DiscoveryRevisionConflict,
)
from request_engine.platform.http.errors import ErrorBody, ErrorEnvelope, ErrorResolution


def _response(body: ErrorBody) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content=ErrorEnvelope(error=body).model_dump(mode="json"),
    )


async def discovery_operational_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, DiscoveryRevisionConflict):
        return _response(
            ErrorBody(
                code="discovery_revision_conflict",
                message="the discovery configuration changed",
                resolution=ErrorResolution.REFRESH_AND_RETRY,
                details={
                    "aggregate_id": str(exc.aggregate_id),
                    "expected_revision": exc.expected,
                    "current_revision": exc.actual,
                },
            )
        )
    if isinstance(exc, DiscoveryConfigurationConflict):
        return _response(
            ErrorBody(
                code="discovery_configuration_conflict",
                message="the discovery configuration conflicts with current state",
                resolution=ErrorResolution.REFRESH_AND_RETRY,
                details={"reason": exc.reason},
            )
        )
    raise exc
