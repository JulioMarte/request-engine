from fastapi import Request, status
from fastapi.responses import JSONResponse

from request_engine.modules.queue.contracts.intake import QueueIntakeStopped
from request_engine.platform.http.errors import ErrorBody, ErrorEnvelope, ErrorResolution


async def queue_intake_stopped_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, QueueIntakeStopped):
        raise exc
    body = ErrorBody(
        code="queue_intake_stopped",
        message="this service queue is not accepting new intake",
        resolution=ErrorResolution.OPERATOR_INTERVENTION,
        details={
            "service_queue_id": str(exc.service_queue_id),
            "reason": exc.reason,
        },
    )
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content=ErrorEnvelope(error=body).model_dump(mode="json"),
    )
