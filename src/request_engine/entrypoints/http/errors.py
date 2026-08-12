from typing import Protocol, runtime_checkable

from fastapi import Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from request_engine.entrypoints.http.request_models import ErrorBody, ErrorEnvelope
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
)
from request_engine.modules.queue.application.errors import (
    ActiveQueueEntryNotFound,
    AlreadyInQueue,
    QueueEntryNotCancellable,
    QueueError,
    QueueInactive,
    QueueNotFound,
)
from request_engine.modules.requests.application.errors import (
    ExternalCorrelationConflict,
    RequestDefinitionInactive,
    RequestDefinitionNotFound,
    RequestDefinitionVersionNotFound,
    RequestError,
    RequestNotFound,
    RequestNotOpen,
    RequestPartyNotUsable,
    RequestPayloadInvalid,
    RequestResultAlreadyRecorded,
    RequestResultNotDefined,
    RequestResultRequired,
    RequestRevisionConflict,
    UnsupportedRequestSchema,
)


@runtime_checkable
class _HasSqlState(Protocol):
    sqlstate: str | None


async def request_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestError):
        raise exc
    status_code, body = _request_error(exc)
    return _response(status_code, body)


async def booking_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, BookingError):
        raise exc
    status_code, body = _booking_error(exc)
    return _response(status_code, body)


async def queue_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, QueueError):
        raise exc
    status_code, body = _queue_error(exc)
    return _response(status_code, body)


async def integrity_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, IntegrityError):
        raise exc
    sqlstate = exc.orig.sqlstate if isinstance(exc.orig, _HasSqlState) else None
    if sqlstate == "23505":
        body = ErrorBody(
            code="conflict",
            message="the command conflicts with existing authoritative state",
        )
        return _response(status.HTTP_409_CONFLICT, body)
    body = ErrorBody(
        code="database_integrity_error",
        message="the command violated an authoritative database invariant",
    )
    return _response(status.HTTP_500_INTERNAL_SERVER_ERROR, body)


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
    if isinstance(exc, OfferingVersionNotBookable):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="offering_not_bookable",
            message=str(exc),
            details={"offering_version_id": str(exc.offering_version_id)},
        )
    if isinstance(exc, AppointmentUnavailable):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="appointment_unavailable",
            message=str(exc),
            details={"reason": exc.reason},
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
            code="invalid_resource_selection",
            message=str(exc),
            details={"reason": exc.reason},
        )
    if isinstance(exc, BookingConfigurationError):
        return status.HTTP_500_INTERNAL_SERVER_ERROR, ErrorBody(
            code="booking_configuration_error",
            message="the configured booking capability is invalid",
            details={"reason": exc.reason},
        )
    return status.HTTP_500_INTERNAL_SERVER_ERROR, ErrorBody(
        code="booking_error",
        message="the booking command failed",
    )


def _queue_error(exc: QueueError) -> tuple[int, ErrorBody]:
    if isinstance(exc, QueueNotFound):
        return status.HTTP_404_NOT_FOUND, ErrorBody(
            code="queue_not_found",
            message=str(exc),
            details={"queue_id": str(exc.queue_id)},
        )
    if isinstance(exc, QueueInactive):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="queue_inactive",
            message=str(exc),
            details={"queue_id": str(exc.queue_id)},
        )
    if isinstance(exc, AlreadyInQueue):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="already_in_queue",
            message=str(exc),
            details={
                "queue_id": str(exc.queue_id),
                "subject_party_id": str(exc.subject_party_id),
            },
        )
    if isinstance(exc, ActiveQueueEntryNotFound):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="active_queue_entry_not_found",
            message=str(exc),
            details={
                "queue_id": str(exc.queue_id),
                "subject_party_id": str(exc.subject_party_id),
            },
        )
    if isinstance(exc, QueueEntryNotCancellable):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="queue_entry_not_cancellable",
            message=str(exc),
            details={"entry_id": str(exc.entry_id), "status": exc.status},
        )
    return status.HTTP_500_INTERNAL_SERVER_ERROR, ErrorBody(
        code="queue_error",
        message="the queue command failed",
    )


def _request_error(exc: RequestError) -> tuple[int, ErrorBody]:
    if isinstance(exc, RequestDefinitionNotFound):
        return status.HTTP_404_NOT_FOUND, ErrorBody(
            code="request_definition_not_found",
            message=str(exc),
            details={"request_key": exc.request_key, "version": exc.version},
        )
    if isinstance(exc, RequestDefinitionVersionNotFound):
        return status.HTTP_404_NOT_FOUND, ErrorBody(
            code="request_definition_version_not_found",
            message=str(exc),
            details={"version_id": str(exc.version_id)},
        )
    if isinstance(exc, RequestNotFound):
        return status.HTTP_404_NOT_FOUND, ErrorBody(
            code="request_not_found",
            message=str(exc),
            details={"request_id": str(exc.request_id)},
        )
    if isinstance(exc, RequestPayloadInvalid):
        return status.HTTP_422_UNPROCESSABLE_CONTENT, ErrorBody(
            code="request_payload_invalid",
            message=str(exc),
            details={"path": exc.path, "reason": exc.reason},
        )
    if isinstance(exc, RequestPartyNotUsable):
        return status.HTTP_422_UNPROCESSABLE_CONTENT, ErrorBody(
            code="request_party_not_usable",
            message=str(exc),
            details={"party_id": str(exc.party_id)},
        )
    if isinstance(exc, UnsupportedRequestSchema):
        return status.HTTP_500_INTERNAL_SERVER_ERROR, ErrorBody(
            code="request_definition_invalid",
            message="the configured Request definition uses an unsupported schema",
            details={"path": exc.path, "keyword": exc.keyword},
        )
    if isinstance(exc, RequestRevisionConflict):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="request_revision_conflict",
            message=str(exc),
            details={
                "request_id": str(exc.request_id),
                "expected_revision": exc.expected,
                "current_revision": exc.actual,
            },
        )
    if isinstance(exc, RequestNotOpen):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="request_not_open",
            message=str(exc),
            details={"request_id": str(exc.request_id), "status": exc.status},
        )
    if isinstance(exc, ExternalCorrelationConflict):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="external_correlation_conflict",
            message=str(exc),
            details={
                "correlation_kind": exc.correlation_kind,
                "provider_key": exc.provider_key,
                "external_key": exc.external_key,
            },
        )
    if isinstance(exc, RequestResultAlreadyRecorded):
        return _request_conflict("request_result_already_recorded", exc)
    if isinstance(exc, RequestResultRequired):
        return _request_conflict("request_result_required", exc)
    if isinstance(exc, RequestResultNotDefined):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="request_result_not_defined",
            message=str(exc),
            details={"version_id": str(exc.version_id)},
        )
    if isinstance(exc, RequestDefinitionInactive):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="request_definition_inactive",
            message=str(exc),
            details={"version_id": str(exc.version_id)},
        )
    return status.HTTP_500_INTERNAL_SERVER_ERROR, ErrorBody(
        code="request_error",
        message="the Request command failed",
    )


def _request_conflict(
    code: str,
    exc: RequestResultAlreadyRecorded | RequestResultRequired,
) -> tuple[int, ErrorBody]:
    return status.HTTP_409_CONFLICT, ErrorBody(
        code=code,
        message=str(exc),
        details={"request_id": str(exc.request_id)},
    )


def _response(status_code: int, body: ErrorBody) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=ErrorEnvelope(error=body).model_dump())
