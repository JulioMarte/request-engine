from fastapi import Request, status
from fastapi.responses import JSONResponse

from request_engine.modules.catalog.application.errors import (
    CatalogConfigurationConflict,
    LocationOperationalRevisionConflict,
)
from request_engine.platform.http.errors import ErrorBody, ErrorEnvelope, ErrorResolution


def _response(body: ErrorBody) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content=ErrorEnvelope(error=body).model_dump(mode="json"),
    )


async def catalog_operational_error_handler(
    _: Request,
    exc: Exception,
) -> JSONResponse:
    if isinstance(exc, LocationOperationalRevisionConflict):
        return _response(
            ErrorBody(
                code="location_operational_revision_conflict",
                message="the Location operational configuration changed",
                resolution=ErrorResolution.REFRESH_AND_RETRY,
                details={
                    "location_id": str(exc.location_id),
                    "expected_revision": exc.expected,
                    "current_revision": exc.actual,
                },
            )
        )
    if isinstance(exc, CatalogConfigurationConflict):
        return _response(
            ErrorBody(
                code="catalog_configuration_conflict",
                message="the catalog configuration conflicts with current state",
                resolution=ErrorResolution.REFRESH_AND_RETRY,
                details={"reason": exc.reason},
            )
        )
    raise exc
