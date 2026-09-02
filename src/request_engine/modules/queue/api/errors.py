from fastapi import Request, status
from fastapi.responses import JSONResponse

from request_engine.modules.queue.application.errors import (
    ActiveQueueEntryNotFound,
    AlreadyInQueue,
    QueueEntryNotCancellable,
    QueueEntryNotFound,
    QueueEntryRevisionConflict,
    QueueError,
    QueueInactive,
    QueueNotFound,
    SubjectAuthorityRequired,
    TenantReferenceNotUsable,
)
from request_engine.platform.http.errors import ErrorBody, ErrorEnvelope, ErrorResolution


async def queue_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, QueueError):
        raise exc
    from request_engine.modules.queue.api.error_handler import resolve_queue_error

    status_code, body = resolve_queue_error(exc)
    return JSONResponse(
        status_code=status_code,
        content=ErrorEnvelope(error=body).model_dump(mode="json"),
    )


def core_queue_error(exc: QueueError) -> tuple[int, ErrorBody] | None:
    if isinstance(exc, TenantReferenceNotUsable):
        return status.HTTP_422_UNPROCESSABLE_CONTENT, ErrorBody(
            code="tenant_reference_not_usable",
            message="a referenced entity is not usable for this tenant",
            resolution=ErrorResolution.FIX_REQUEST,
            details={"reference_kind": exc.reference_kind},
        )
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
    if isinstance(exc, QueueInactive):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="queue_inactive",
            message=str(exc),
            resolution=ErrorResolution.CHOOSE_ALTERNATIVE,
            details={"queue_id": str(exc.queue_id)},
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
    return None


# Frozen V3 provenance: the public fallback code remains literal in this module.
_FROZEN_QUEUE_FALLBACK = ErrorBody(
    code="queue_error",
    message="the queue command failed",
    resolution=ErrorResolution.OPERATOR_INTERVENTION,
)
