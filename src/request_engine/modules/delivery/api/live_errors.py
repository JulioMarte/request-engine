from fastapi import Request, status
from fastapi.responses import JSONResponse

from request_engine.modules.delivery.application.errors import (
    LiveServiceError,
    LiveServiceRevisionConflict,
    QueueEntryNotCallable,
    ResourceActivityNotFound,
    ResourceExecutionUnavailable,
    ServiceSessionNotActionable,
    ServiceSessionNotFound,
    WorkloadClassificationUnavailable,
)
from request_engine.platform.http.errors import ErrorBody, ErrorEnvelope, ErrorResolution


async def live_service_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, LiveServiceError):
        raise exc
    code = status.HTTP_409_CONFLICT
    resolution = ErrorResolution.REFRESH_AND_RETRY
    error_code = "live_service_conflict"
    message = str(exc)
    details: dict[str, object] = {}
    if isinstance(exc, ServiceSessionNotFound):
        code = status.HTTP_404_NOT_FOUND
        error_code = "service_session_not_found"
        message = "ServiceSession not found"
    elif isinstance(exc, ResourceActivityNotFound):
        code = status.HTTP_404_NOT_FOUND
        error_code = "resource_activity_not_found"
        message = "ResourceActivity not found"
    elif isinstance(exc, LiveServiceRevisionConflict):
        error_code = "revision_conflict"
        details = {
            "aggregate_id": str(exc.aggregate_id),
            "expected_revision": exc.expected,
            "current_revision": exc.actual,
        }
    elif isinstance(exc, QueueEntryNotCallable):
        error_code = "queue_entry_not_callable"
        details = {"queue_entry_id": str(exc.queue_entry_id), "status": exc.status}
    elif isinstance(exc, ServiceSessionNotActionable):
        error_code = "service_session_not_actionable"
        details = {
            "service_session_id": str(exc.service_session_id),
            "status": exc.status,
            "action": exc.action,
        }
    elif isinstance(exc, ResourceExecutionUnavailable):
        error_code = "resource_execution_unavailable"
        resolution = ErrorResolution.CHOOSE_ALTERNATIVE
        details = {"resource_id": str(exc.resource_id), "reason": exc.reason}
    elif isinstance(exc, WorkloadClassificationUnavailable):
        code = status.HTTP_422_UNPROCESSABLE_CONTENT
        error_code = "workload_classification_unavailable"
        resolution = ErrorResolution.CHOOSE_ALTERNATIVE
        details = {"workload_classification_id": str(exc.workload_id)}
    body = ErrorBody(code=error_code, message=message, resolution=resolution, details=details)
    return JSONResponse(status_code=code, content=ErrorEnvelope(error=body).model_dump(mode="json"))
