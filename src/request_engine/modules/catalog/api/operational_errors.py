from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from request_engine.modules.catalog.application.errors import (
    CatalogConfigurationConflict,
    CatalogInvalidInput,
    LocationOperationalRevisionConflict,
    OfferingBookingPolicyRevisionConflict,
)
from request_engine.platform.http.errors import ErrorBody, ErrorEnvelope, ErrorResolution


def register_input_error_handler(app: FastAPI) -> None:
    app.add_exception_handler(CatalogInvalidInput, catalog_input_error_handler)


async def catalog_input_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, CatalogInvalidInput):
        raise exc
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content=ErrorEnvelope(
            error=ErrorBody(
                code="invalid_catalog_input",
                message=str(exc),
                retryable=False,
                resolution=ErrorResolution.FIX_REQUEST,
            )
        ).model_dump(mode="json"),
    )


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
    if isinstance(exc, OfferingBookingPolicyRevisionConflict):
        return _response(
            ErrorBody(
                code="offering_booking_policy_revision_conflict",
                message="the OfferingVersion booking policy changed",
                resolution=ErrorResolution.REFRESH_AND_RETRY,
                details={
                    "offering_version_id": str(exc.offering_version_id),
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
