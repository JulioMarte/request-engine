from fastapi import Request, status
from fastapi.responses import JSONResponse

from request_engine.modules.queue.application.errors import (
    ActiveQueueEntryNotFound,
    AlreadyInQueue,
    AlreadyOnWaitlist,
    OfferingNotAvailableForWaitlist,
    QueueEntryNotCancellable,
    QueueEntryNotFound,
    QueueEntryRevisionConflict,
    QueueError,
    QueueInactive,
    QueueNotFound,
    SlotOpportunitySourceConflict,
    SubjectAuthorityRequired,
    WaitlistEntryNotCancellable,
    WaitlistEntryNotFound,
    WaitlistEntryRevisionConflict,
)
from request_engine.platform.http.errors import ErrorBody, ErrorEnvelope, ErrorResolution


async def queue_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, QueueError):
        raise exc
    status_code, body = _queue_error(exc)
    return JSONResponse(
        status_code=status_code,
        content=ErrorEnvelope(error=body).model_dump(mode="json"),
    )


def _queue_error(exc: QueueError) -> tuple[int, ErrorBody]:
    if isinstance(exc, SubjectAuthorityRequired):
        return status.HTTP_403_FORBIDDEN, ErrorBody(
            code="party_authority_required",
            message=str(exc),
            resolution=ErrorResolution.REQUEST_AUTHORITY,
            details={
                "party_id": str(exc.subject_party_id),
                "authority_anchor": "subject",
                "scope_key": exc.scope_key,
            },
        )
    if isinstance(exc, QueueNotFound):
        return status.HTTP_404_NOT_FOUND, ErrorBody(
            code="queue_not_found",
            message=str(exc),
            resolution=ErrorResolution.FIX_REQUEST,
            details={"queue_id": str(exc.queue_id)},
        )
    if isinstance(exc, QueueEntryNotFound):
        return status.HTTP_404_NOT_FOUND, ErrorBody(
            code="queue_entry_not_found",
            message=str(exc),
            resolution=ErrorResolution.REFRESH_AND_RETRY,
            details={
                "queue_id": str(exc.queue_id),
                "queue_entry_id": str(exc.entry_id),
            },
        )
    if isinstance(exc, WaitlistEntryNotFound):
        return status.HTTP_404_NOT_FOUND, ErrorBody(
            code="waitlist_entry_not_found",
            message=str(exc),
            resolution=ErrorResolution.REFRESH_AND_RETRY,
            details={"waitlist_entry_id": str(exc.entry_id)},
        )
    if isinstance(exc, QueueEntryRevisionConflict):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="revision_conflict",
            message="the aggregate changed since it was read",
            resolution=ErrorResolution.REFRESH_AND_RETRY,
            details={
                "aggregate_kind": "QueueEntry",
                "aggregate_id": str(exc.entry_id),
                "expected_revision": exc.expected,
                "current_revision": exc.actual,
            },
        )
    if isinstance(exc, WaitlistEntryRevisionConflict):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="revision_conflict",
            message="the aggregate changed since it was read",
            resolution=ErrorResolution.REFRESH_AND_RETRY,
            details={
                "aggregate_kind": "WaitlistEntry",
                "aggregate_id": str(exc.entry_id),
                "expected_revision": exc.expected,
                "current_revision": exc.actual,
            },
        )
    if isinstance(exc, QueueInactive):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="queue_inactive",
            message=str(exc),
            resolution=ErrorResolution.CHOOSE_ALTERNATIVE,
            details={"queue_id": str(exc.queue_id)},
        )
    if isinstance(exc, OfferingNotAvailableForWaitlist):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="offering_not_available_for_waitlist",
            message=str(exc),
            resolution=ErrorResolution.CHOOSE_ALTERNATIVE,
            details={"offering_id": str(exc.offering_id)},
        )
    if isinstance(exc, AlreadyInQueue):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="already_in_queue",
            message=str(exc),
            resolution=ErrorResolution.REFRESH_AND_RETRY,
            details={
                "queue_id": str(exc.queue_id),
                "subject_party_id": str(exc.subject_party_id),
            },
        )
    if isinstance(exc, AlreadyOnWaitlist):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="already_on_waitlist",
            message=str(exc),
            resolution=ErrorResolution.REFRESH_AND_RETRY,
            details={
                "offering_id": str(exc.offering_id),
                "subject_party_id": str(exc.subject_party_id),
            },
        )
    if isinstance(exc, ActiveQueueEntryNotFound):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="active_queue_entry_not_found",
            message=str(exc),
            resolution=ErrorResolution.REFRESH_AND_RETRY,
            details={
                "queue_id": str(exc.queue_id),
                "subject_party_id": str(exc.subject_party_id),
            },
        )
    if isinstance(exc, QueueEntryNotCancellable):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="queue_entry_not_cancellable",
            message=str(exc),
            resolution=ErrorResolution.REFRESH_AND_RETRY,
            details={"entry_id": str(exc.entry_id), "status": exc.status},
        )
    if isinstance(exc, WaitlistEntryNotCancellable):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="waitlist_entry_not_cancellable",
            message=str(exc),
            resolution=ErrorResolution.REFRESH_AND_RETRY,
            details={"entry_id": str(exc.entry_id), "status": exc.status},
        )
    if isinstance(exc, SlotOpportunitySourceConflict):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="slot_opportunity_source_conflict",
            message=str(exc),
            resolution=ErrorResolution.OPERATOR_INTERVENTION,
            details={"source_event_id": str(exc.source_event_id)},
        )
    return status.HTTP_500_INTERNAL_SERVER_ERROR, ErrorBody(
        code="queue_error",
        message="the queue command failed",
        resolution=ErrorResolution.OPERATOR_INTERVENTION,
    )
