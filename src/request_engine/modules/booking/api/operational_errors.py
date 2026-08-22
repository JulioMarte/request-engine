from fastapi import Request, status
from fastapi.responses import JSONResponse

from request_engine.modules.booking.application.operational_errors import (
    ContextualConfigurationConflict,
    ResourceAvailabilityRevisionConflict,
    ResourceLocationAssignmentRevisionConflict,
)
from request_engine.platform.http.errors import ErrorBody, ErrorEnvelope, ErrorResolution

BookingOperationalError = (
    ResourceAvailabilityRevisionConflict
    | ResourceLocationAssignmentRevisionConflict
    | ContextualConfigurationConflict
)


def _response(body: ErrorBody) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content=ErrorEnvelope(error=body).model_dump(mode="json"),
    )


async def booking_operational_error_handler(
    _: Request,
    exc: Exception,
) -> JSONResponse:
    if isinstance(exc, ResourceAvailabilityRevisionConflict):
        return _response(
            ErrorBody(
                code="resource_availability_revision_conflict",
                message="the Resource availability configuration changed",
                resolution=ErrorResolution.REFRESH_AND_RETRY,
                details={
                    "resource_id": str(exc.resource_id),
                    "expected_revision": exc.expected,
                    "current_revision": exc.actual,
                },
            )
        )
    if isinstance(exc, ResourceLocationAssignmentRevisionConflict):
        return _response(
            ErrorBody(
                code="resource_location_assignment_revision_conflict",
                message="the ResourceLocationAssignment changed",
                resolution=ErrorResolution.REFRESH_AND_RETRY,
                details={
                    "assignment_id": str(exc.assignment_id),
                    "expected_revision": exc.expected,
                    "current_revision": exc.actual,
                },
            )
        )
    if isinstance(exc, ContextualConfigurationConflict):
        return _response(
            ErrorBody(
                code="contextual_configuration_conflict",
                message="the contextual supply configuration conflicts with current state",
                resolution=ErrorResolution.REFRESH_AND_RETRY,
                details={"reason": exc.reason},
            )
        )
    raise exc
