from fastapi import status

from request_engine.modules.queue.application.errors import QueueError
from request_engine.modules.queue.application.triage_errors import (
    InvalidRecallHold,
    QueueEntryAlreadyHeld,
    QueueEntryAlreadySkipped,
    QueueEntryNotCurrentHead,
    QueueEntryNotWaiting,
    TriageQueueEntryNotFound,
)
from request_engine.platform.http.errors import ErrorBody, ErrorResolution


def triage_error(exc: QueueError) -> tuple[int, ErrorBody] | None:
    if isinstance(exc, TriageQueueEntryNotFound):
        return status.HTTP_404_NOT_FOUND, ErrorBody(
            code="queue_entry_not_found",
            message=str(exc),
            resolution=ErrorResolution.REFRESH_AND_RETRY,
            details={"queue_entry_id": str(exc.entry_id)},
        )
    if isinstance(exc, QueueEntryNotWaiting):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="queue_entry_not_waiting",
            message=str(exc),
            resolution=ErrorResolution.REFRESH_AND_RETRY,
            details={"queue_entry_id": str(exc.entry_id), "status": exc.status},
        )
    if isinstance(exc, QueueEntryNotCurrentHead):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="queue_entry_not_current_head",
            message=str(exc),
            resolution=ErrorResolution.REFRESH_AND_RETRY,
            details={"queue_entry_id": str(exc.entry_id)},
        )
    if isinstance(exc, QueueEntryAlreadyHeld):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="queue_entry_already_held",
            message=str(exc),
            resolution=ErrorResolution.REFRESH_AND_RETRY,
            details={"queue_entry_id": str(exc.entry_id)},
        )
    if isinstance(exc, QueueEntryAlreadySkipped):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="queue_entry_already_skipped",
            message=str(exc),
            resolution=ErrorResolution.REFRESH_AND_RETRY,
            details={"queue_entry_id": str(exc.entry_id)},
        )
    if isinstance(exc, InvalidRecallHold):
        return status.HTTP_422_UNPROCESSABLE_CONTENT, ErrorBody(
            code="invalid_recall_hold",
            message=str(exc),
            resolution=ErrorResolution.FIX_REQUEST,
        )
    return None
