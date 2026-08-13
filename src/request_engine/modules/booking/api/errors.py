from fastapi import Request, status
from fastapi.responses import JSONResponse

from request_engine.modules.booking.application.errors import (
    AppointmentUnavailable,
    BookingConfigurationError,
    BookingError,
    InvalidResourceSelection,
    OfferingVersionNotBookable,
    OfferingVersionNotFound,
    ReservationNotCancellable,
    ReservationNotFound,
    ReservationNotReschedulable,
    ReservationRevisionConflict,
    SubjectAuthorityRequired,
)
from request_engine.platform.http.errors import ErrorBody, ErrorEnvelope


async def booking_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, BookingError):
        raise exc
    status_code, body = _booking_error(exc)
    return JSONResponse(status_code=status_code, content=ErrorEnvelope(error=body).model_dump())


def _booking_error(exc: BookingError) -> tuple[int, ErrorBody]:
    if isinstance(exc, OfferingVersionNotFound):
        return status.HTTP_404_NOT_FOUND, ErrorBody(
            code="offering_version_not_found",
            message=str(exc),
            details={"offering_version_id": str(exc.offering_version_id)},
        )
    if isinstance(exc, ReservationNotFound):
        return status.HTTP_404_NOT_FOUND, ErrorBody(
            code="reservation_not_found",
            message=str(exc),
            details={"reservation_id": str(exc.reservation_id)},
        )
    if isinstance(exc, SubjectAuthorityRequired):
        return status.HTTP_403_FORBIDDEN, ErrorBody(
            code="subject_authority_required",
            message="the actor is not authorized to act for this Party",
            details={
                "subject_party_id": str(exc.subject_party_id),
                "scope_key": exc.scope_key,
            },
        )
    if isinstance(exc, ReservationRevisionConflict):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="revision_conflict",
            message="the aggregate changed since it was read",
            details={
                "aggregate_kind": "Reservation",
                "aggregate_id": str(exc.reservation_id),
                "expected_revision": exc.expected,
                "current_revision": exc.actual,
            },
        )
    if isinstance(exc, OfferingVersionNotBookable):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="offering_not_bookable",
            message=str(exc),
            details={"offering_version_id": str(exc.offering_version_id)},
        )
    if isinstance(exc, AppointmentUnavailable):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="appointment_unavailable", message=str(exc), details={"reason": exc.reason}
        )
    if isinstance(exc, ReservationNotCancellable):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="reservation_not_cancellable",
            message=str(exc),
            details={"reservation_id": str(exc.reservation_id), "status": exc.status},
        )
    if isinstance(exc, ReservationNotReschedulable):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="reservation_not_reschedulable",
            message=str(exc),
            details={"reservation_id": str(exc.reservation_id), "status": exc.status},
        )
    if isinstance(exc, InvalidResourceSelection):
        return status.HTTP_422_UNPROCESSABLE_CONTENT, ErrorBody(
            code="invalid_resource_selection", message=str(exc), details={"reason": exc.reason}
        )
    if isinstance(exc, BookingConfigurationError):
        return status.HTTP_500_INTERNAL_SERVER_ERROR, ErrorBody(
            code="booking_configuration_error",
            message="the configured booking capability is invalid",
            details={"reason": exc.reason},
        )
    return status.HTTP_500_INTERNAL_SERVER_ERROR, ErrorBody(
        code="booking_error", message="the booking command failed"
    )
