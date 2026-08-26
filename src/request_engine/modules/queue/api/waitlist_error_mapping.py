from fastapi import status

from request_engine.modules.queue.application.errors import (
    AlreadyOnWaitlist,
    OfferingNotAvailableForWaitlist,
    QueueError,
    SlotOpportunitySourceConflict,
    WaitlistEntryNotCancellable,
    WaitlistEntryNotFound,
    WaitlistEntryRevisionConflict,
)
from request_engine.platform.http.errors import ErrorBody, ErrorResolution


def waitlist_error(exc: QueueError) -> tuple[int, ErrorBody] | None:
    if isinstance(exc, WaitlistEntryNotFound):
        return status.HTTP_404_NOT_FOUND, ErrorBody(
            code="waitlist_entry_not_found",
            message=str(exc),
            resolution=ErrorResolution.REFRESH_AND_RETRY,
            details={"waitlist_entry_id": str(exc.entry_id)},
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
    if isinstance(exc, OfferingNotAvailableForWaitlist):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="offering_not_available_for_waitlist",
            message=str(exc),
            resolution=ErrorResolution.CHOOSE_ALTERNATIVE,
            details={"offering_id": str(exc.offering_id)},
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
    return None
