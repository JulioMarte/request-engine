from fastapi import status

from request_engine.modules.queue.application.errors import QueueError
from request_engine.modules.queue.application.live_errors import (
    QueueEntryNotClassifiable,
    WorkloadClassificationInactive,
    WorkloadClassificationNotFound,
    WorkloadClassificationRevisionConflict,
    WorkloadKeyConflict,
)
from request_engine.platform.http.errors import ErrorBody, ErrorResolution


def live_queue_error(exc: QueueError) -> tuple[int, ErrorBody] | None:
    if isinstance(exc, QueueEntryNotClassifiable):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="queue_entry_not_classifiable",
            message="expected workload can only change before service starts",
            resolution=ErrorResolution.REFRESH_AND_RETRY,
            details={"entry_id": str(exc.entry_id), "status": exc.status},
        )
    if isinstance(exc, WorkloadClassificationNotFound):
        return status.HTTP_404_NOT_FOUND, ErrorBody(
            code="workload_classification_not_found",
            message="operational workload classification not found",
            resolution=ErrorResolution.REFRESH_AND_RETRY,
            details={"workload_id": str(exc.workload_id)},
        )
    if isinstance(exc, WorkloadClassificationRevisionConflict):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="revision_conflict",
            message="the aggregate changed since it was read",
            resolution=ErrorResolution.REFRESH_AND_RETRY,
            details={
                "aggregate_kind": "OperationalWorkloadClassification",
                "aggregate_id": str(exc.workload_id),
                "expected_revision": exc.expected,
                "current_revision": exc.actual,
            },
        )
    if isinstance(exc, WorkloadClassificationInactive):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="workload_classification_inactive",
            message="inactive operational workload classifications are immutable",
            resolution=ErrorResolution.CHOOSE_ALTERNATIVE,
            details={"workload_id": str(exc.workload_id)},
        )
    if isinstance(exc, WorkloadKeyConflict):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="workload_key_conflict",
            message="operational workload key already exists",
            resolution=ErrorResolution.FIX_REQUEST,
            details={"workload_key": exc.workload_key},
        )
    return None
