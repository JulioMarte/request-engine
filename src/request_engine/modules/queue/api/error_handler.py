from fastapi import status

from request_engine.modules.queue.api.errors import core_queue_error
from request_engine.modules.queue.api.live_error_mapping import live_queue_error
from request_engine.modules.queue.api.same_day_selection_error_mapping import (
    same_day_selection_error,
)
from request_engine.modules.queue.api.waitlist_error_mapping import waitlist_error
from request_engine.modules.queue.application.errors import QueueError
from request_engine.platform.http.errors import ErrorBody, ErrorResolution


def resolve_queue_error(exc: QueueError) -> tuple[int, ErrorBody]:
    for mapper in (
        waitlist_error,
        live_queue_error,
        same_day_selection_error,
        core_queue_error,
    ):
        mapped = mapper(exc)
        if mapped is not None:
            return mapped
    return status.HTTP_500_INTERNAL_SERVER_ERROR, ErrorBody(
        code="queue_error",
        message="the queue command failed",
        resolution=ErrorResolution.OPERATOR_INTERVENTION,
    )
