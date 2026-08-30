from fastapi import Request, status
from fastapi.responses import JSONResponse

from request_engine.modules.operational_recovery.contracts.workflow import (
    RecoveryActionConflict,
    RecoveryIncidentNotFound,
    RecoveryIncidentStale,
    RecoveryOwnerRevisionConflict,
    RecoveryQueueNotFound,
)
from request_engine.platform.http.errors import ErrorBody, ErrorEnvelope, ErrorResolution


async def workflow_recovery_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, RecoveryQueueNotFound):
        body = ErrorBody(
            code="recovery_queue_not_found",
            message="the requested service queue was not found",
            resolution=ErrorResolution.FIX_REQUEST,
            details={"queue_id": str(exc.queue_id)},
        )
        return _response(status.HTTP_404_NOT_FOUND, body)
    if isinstance(exc, RecoveryIncidentNotFound):
        body = ErrorBody(
            code="recovery_incident_not_found",
            message="the requested recovery incident was not found",
            resolution=ErrorResolution.FIX_REQUEST,
            details={"incident_id": str(exc.incident_id)},
        )
        return _response(status.HTTP_404_NOT_FOUND, body)
    if isinstance(exc, RecoveryIncidentStale):
        body = ErrorBody(
            code="STALE_RECOVERY_INCIDENT",
            message="the recovery incident no longer matches authoritative operational state",
            resolution=ErrorResolution.REFRESH_AND_RETRY,
            details={"expected_revision": exc.expected, "actual_revision": exc.actual},
        )
        return _response(status.HTTP_409_CONFLICT, body)
    if isinstance(exc, RecoveryOwnerRevisionConflict):
        body = ErrorBody(
            code="RECOVERY_OWNER_REVISION_CONFLICT",
            message="an authoritative recovery owner changed after this action was authorized",
            resolution=ErrorResolution.REFRESH_AND_RETRY,
            details={
                "owner": exc.owner,
                "scope_id": str(exc.scope_id),
                "expected_revision": exc.expected,
                "actual_revision": exc.actual,
            },
        )
        return _response(status.HTTP_409_CONFLICT, body)
    if isinstance(exc, RecoveryActionConflict):
        body = ErrorBody(
            code="RECOVERY_ACTION_CONFLICT",
            message="the recovery action cannot advance from its current durable state",
            resolution=ErrorResolution.REFRESH_AND_RETRY,
        )
        return _response(status.HTTP_409_CONFLICT, body)
    raise exc


def _response(status_code: int, body: ErrorBody) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=ErrorEnvelope(error=body).model_dump(mode="json"),
    )
