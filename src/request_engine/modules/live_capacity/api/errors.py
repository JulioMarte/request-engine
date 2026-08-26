from fastapi import Request, status
from fastapi.responses import JSONResponse

from request_engine.modules.live_capacity.application.errors import (
    CustomerProjectionTargetNotFound,
    InvalidProjectionConfiguration,
    InvalidWorkloadEstimateConfiguration,
    LiveCapacityError,
    PolicyRevisionConflict,
    ProjectionPolicyNotFound,
    ProjectionScopeAlreadyConfigured,
    ProjectionScopeNotConfigured,
    WorkloadEstimateAlreadyConfigured,
    WorkloadEstimatePolicyNotFound,
)
from request_engine.platform.http.errors import ErrorBody, ErrorEnvelope, ErrorResolution


async def live_capacity_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, LiveCapacityError):
        raise exc
    status_code, body = _map_error(exc)
    return JSONResponse(
        status_code=status_code,
        content=ErrorEnvelope(error=body).model_dump(mode="json"),
    )


def _map_error(exc: LiveCapacityError) -> tuple[int, ErrorBody]:
    if isinstance(exc, PolicyRevisionConflict):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="revision_conflict",
            message="the live-capacity policy changed since it was read",
            resolution=ErrorResolution.REFRESH_AND_RETRY,
            details={"expected_revision": exc.expected_revision},
        )
    if isinstance(exc, ProjectionScopeAlreadyConfigured):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="projection_scope_already_configured",
            message="the service queue already has a projection scope",
            resolution=ErrorResolution.REFRESH_AND_RETRY,
            details={"service_queue_id": str(exc.service_queue_id)},
        )
    if isinstance(exc, ProjectionScopeNotConfigured):
        return status.HTTP_404_NOT_FOUND, ErrorBody(
            code="projection_scope_not_configured",
            message="the service queue does not have an active projection scope",
            resolution=ErrorResolution.OPERATOR_INTERVENTION,
            details={"service_queue_id": str(exc.service_queue_id)},
        )
    if isinstance(exc, CustomerProjectionTargetNotFound):
        return status.HTTP_404_NOT_FOUND, ErrorBody(
            code="customer_projection_target_not_found",
            message="the authorized subject has no active queue entry for this projection",
            resolution=ErrorResolution.FIX_REQUEST,
            details={"service_queue_id": str(exc.service_queue_id)},
        )
    if isinstance(exc, InvalidProjectionConfiguration):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="invalid_projection_configuration",
            message="the configured Resource and Location scope is not operationally valid",
            resolution=ErrorResolution.OPERATOR_INTERVENTION,
            details={"service_queue_id": str(exc.service_queue_id)},
        )
    if isinstance(exc, InvalidWorkloadEstimateConfiguration):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="invalid_workload_estimate_configuration",
            message="the workload classification is not active and valid for estimate policy",
            resolution=ErrorResolution.OPERATOR_INTERVENTION,
            details={"workload_classification_id": str(exc.workload_classification_id)},
        )
    if isinstance(exc, WorkloadEstimateAlreadyConfigured):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="workload_estimate_already_configured",
            message="the workload already has an estimate policy",
            resolution=ErrorResolution.REFRESH_AND_RETRY,
            details={"workload_classification_id": str(exc.workload_classification_id)},
        )
    details: dict[str, object]
    if isinstance(exc, ProjectionPolicyNotFound):
        details = {"policy_id": str(exc.policy_id)}
        code = "projection_policy_not_found"
    elif isinstance(exc, WorkloadEstimatePolicyNotFound):
        details = {"policy_id": str(exc.policy_id)}
        code = "workload_estimate_policy_not_found"
    else:
        return status.HTTP_500_INTERNAL_SERVER_ERROR, ErrorBody(
            code="live_capacity_error",
            message="the live-capacity operation failed",
            resolution=ErrorResolution.OPERATOR_INTERVENTION,
        )
    return status.HTTP_404_NOT_FOUND, ErrorBody(
        code=code,
        message="the requested live-capacity policy was not found",
        resolution=ErrorResolution.FIX_REQUEST,
        details=details,
    )
