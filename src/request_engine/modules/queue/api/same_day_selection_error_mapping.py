from fastapi import status

from request_engine.modules.queue.application.errors import QueueError
from request_engine.modules.queue.application.same_day_selection_errors import (
    QueueEntryNotSelectable,
    QueueEntryRecallHeld,
    RecallHoldConflict,
    RecallHoldInvalid,
)
from request_engine.platform.http.errors import ErrorBody, ErrorResolution


def same_day_selection_error(exc: QueueError) -> tuple[int, ErrorBody] | None:
    if isinstance(exc, QueueEntryNotSelectable):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="queue_entry_not_selectable",
            message=str(exc),
            resolution=ErrorResolution.REFRESH_AND_RETRY,
            details={"queue_entry_id": str(exc.entry_id), "status": exc.status},
        )
    if isinstance(exc, QueueEntryRecallHeld):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="queue_entry_recall_held",
            message=str(exc),
            resolution=ErrorResolution.REFRESH_AND_RETRY,
            details={"queue_entry_id": str(exc.entry_id)},
        )
    if isinstance(exc, RecallHoldConflict):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="recall_hold_conflict",
            message=str(exc),
            resolution=ErrorResolution.REFRESH_AND_RETRY,
            details={
                "queue_entry_id": str(exc.entry_id),
                "requested_hold_id": str(exc.requested_hold_id),
                "active_hold_id": str(exc.active_hold_id),
            },
        )
    if isinstance(exc, RecallHoldInvalid):
        return status.HTTP_422_UNPROCESSABLE_CONTENT, ErrorBody(
            code="recall_hold_invalid",
            message=exc.detail,
            resolution=ErrorResolution.FIX_REQUEST,
        )
    return None
