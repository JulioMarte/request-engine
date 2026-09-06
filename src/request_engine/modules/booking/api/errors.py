from typing import Any

from fastapi import Request, status
from fastapi.responses import JSONResponse

from request_engine.modules.booking.application import errors as booking_errors
from request_engine.platform.http.errors import ErrorBody, ErrorEnvelope, ErrorResolution


async def booking_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, booking_errors.BookingError):
        raise exc
    status_code, body = _booking_error(exc)
    content = ErrorEnvelope(error=body).model_dump(mode="json")
    return JSONResponse(status_code=status_code, content=content)


def _status_conflict_fields(exc: booking_errors.ReservationStateConflict) -> dict[str, Any]:
    return {
        "message": str(exc),
        "resolution": ErrorResolution.REFRESH_AND_RETRY,
        "details": {"reservation_id": str(exc.reservation_id), "status": exc.status},
    }


def _booking_error(exc: booking_errors.BookingError) -> tuple[int, ErrorBody]:
    if isinstance(exc, booking_errors.AppointmentOptionInvalid):
        return status.HTTP_422_UNPROCESSABLE_CONTENT, ErrorBody(
            code="appointment_option_invalid",
            message="the appointment option is invalid for this request",
            resolution=ErrorResolution.FIX_REQUEST,
            details={},
        )
    if isinstance(exc, booking_errors.AppointmentOptionExpired):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="appointment_option_expired",
            message="the appointment option has expired",
            resolution=ErrorResolution.CHOOSE_ALTERNATIVE,
            details={},
        )
    if isinstance(exc, booking_errors.AppointmentOptionStale):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="appointment_option_stale",
            message="the appointment option no longer matches current booking configuration",
            resolution=ErrorResolution.REFRESH_AND_RETRY,
            details={},
        )
    if isinstance(exc, booking_errors.OfferingVersionNotFound):
        return status.HTTP_404_NOT_FOUND, ErrorBody(
            code="offering_version_not_found",
            message=str(exc),
            resolution=ErrorResolution.FIX_REQUEST,
            details={"offering_version_id": str(exc.offering_version_id)},
        )
    if isinstance(exc, booking_errors.ReservationNotFound):
        return status.HTTP_404_NOT_FOUND, ErrorBody(
            code="reservation_not_found",
            message=str(exc),
            resolution=ErrorResolution.REFRESH_AND_RETRY,
            details={"reservation_id": str(exc.reservation_id)},
        )
    if isinstance(exc, booking_errors.SubjectAuthorityRequired):
        return status.HTTP_403_FORBIDDEN, ErrorBody(
            code="party_authority_required",
            message="the actor is not authorized to act for this Party",
            resolution=ErrorResolution.REQUEST_AUTHORITY,
            details={
                "party_id": str(exc.subject_party_id),
                "authority_anchor": "subject",
                "scope_key": exc.scope_key,
            },
        )
    if isinstance(exc, booking_errors.ReservationRevisionConflict):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="revision_conflict",
            message="the aggregate changed since it was read",
            resolution=ErrorResolution.REFRESH_AND_RETRY,
            details={
                "aggregate_kind": "Reservation",
                "aggregate_id": str(exc.reservation_id),
                "expected_revision": exc.expected,
                "current_revision": exc.actual,
            },
        )
    if isinstance(exc, booking_errors.OfferingVersionNotBookable):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="offering_not_bookable",
            message=str(exc),
            resolution=ErrorResolution.CHOOSE_ALTERNATIVE,
            details={"offering_version_id": str(exc.offering_version_id)},
        )
    if isinstance(exc, booking_errors.AppointmentUnavailable):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="appointment_unavailable",
            message="the requested appointment is unavailable",
            resolution=ErrorResolution.CHOOSE_ALTERNATIVE,
            details={},
        )
    if isinstance(exc, booking_errors.ReservationNotConfirmed):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="reservation_not_confirmed", **_status_conflict_fields(exc)
        )
    if isinstance(exc, booking_errors.ReservationNotCancellable):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="reservation_not_cancellable", **_status_conflict_fields(exc)
        )
    if isinstance(exc, booking_errors.ReservationNotReschedulable):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="reservation_not_reschedulable", **_status_conflict_fields(exc)
        )
    if isinstance(exc, booking_errors.ArrivalEstimateInvalid):
        return status.HTTP_422_UNPROCESSABLE_CONTENT, ErrorBody(
            code="arrival_estimate_invalid",
            message=str(exc),
            resolution=ErrorResolution.FIX_REQUEST,
            details={"reservation_id": str(exc.reservation_id), "reason": exc.reason},
        )
    if isinstance(exc, booking_errors.InvalidResourceSelection):
        return status.HTTP_422_UNPROCESSABLE_CONTENT, ErrorBody(
            code="invalid_resource_selection",
            message=str(exc),
            resolution=ErrorResolution.FIX_REQUEST,
            details={"reason": exc.reason},
        )
    if isinstance(exc, booking_errors.BookingConfigurationError):
        return status.HTTP_500_INTERNAL_SERVER_ERROR, ErrorBody(
            code="booking_configuration_error",
            message="the configured booking capability is invalid",
            resolution=ErrorResolution.OPERATOR_INTERVENTION,
            details={"reason": exc.reason},
        )
    return status.HTTP_500_INTERNAL_SERVER_ERROR, ErrorBody(
        code="booking_error",
        message="the booking command failed",
        resolution=ErrorResolution.OPERATOR_INTERVENTION,
    )
