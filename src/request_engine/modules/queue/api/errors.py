from fastapi import Request, status
from fastapi.responses import JSONResponse

from request_engine.modules.queue.application.errors import (
    ActiveQueueEntryNotFound,
    AlreadyInQueue,
    QueueEntryNotCancellable,
    QueueError,
    QueueInactive,
    QueueNotFound,
    SubjectAuthorityRequired,
)
from request_engine.platform.http.errors import ErrorBody, ErrorEnvelope


async def queue_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, QueueError):
        raise exc
    status_code, body = _queue_error(exc)
    return JSONResponse(status_code=status_code, content=ErrorEnvelope(error=body).model_dump())


def _queue_error(exc: QueueError) -> tuple[int, ErrorBody]:
    if isinstance(exc, SubjectAuthorityRequired):
        return status.HTTP_403_FORBIDDEN, ErrorBody(
            code="subject_authority_required",
            message=str(exc),
            details={
                "subject_party_id": str(exc.subject_party_id),
                "scope_key": exc.scope_key,
            },
        )
    if isinstance(exc, QueueNotFound):
        return status.HTTP_404_NOT_FOUND, ErrorBody(
            code="queue_not_found", message=str(exc), details={"queue_id": str(exc.queue_id)}
        )
    if isinstance(exc, QueueInactive):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="queue_inactive", message=str(exc), details={"queue_id": str(exc.queue_id)}
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
        code="queue_error", message="the queue command failed"
    )
