from fastapi import Request, status
from fastapi.responses import JSONResponse

from request_engine.modules.communications.application.errors import (
    DeliveryConfigurationError,
    RecipientNotFound,
    ReminderPlanNotActive,
    ReminderPlanNotFound,
    ReminderPlanRevisionConflict,
    ReminderSubjectAuthorityRequired,
)
from request_engine.modules.communications.domain.errors import CommunicationsError
from request_engine.platform.http.errors import ErrorBody, ErrorEnvelope, ErrorResolution


async def communications_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, CommunicationsError):
        raise exc
    status_code, body = resolve_communications_error(exc)
    return JSONResponse(
        status_code=status_code,
        content=ErrorEnvelope(error=body).model_dump(mode="json"),
    )


def resolve_communications_error(exc: CommunicationsError) -> tuple[int, ErrorBody]:
    if isinstance(exc, RecipientNotFound):
        return status.HTTP_422_UNPROCESSABLE_CONTENT, ErrorBody(
            code="tenant_reference_not_usable",
            message="a referenced entity is not usable for this tenant",
            resolution=ErrorResolution.FIX_REQUEST,
            details={"reference_kind": "subject_party_id"},
        )
    if isinstance(exc, ReminderPlanNotFound):
        return status.HTTP_404_NOT_FOUND, ErrorBody(
            code="reminder_plan_not_found",
            message="the ReminderPlan was not found",
            resolution=ErrorResolution.REFRESH_AND_RETRY,
            details={"reminder_plan_id": str(exc.reminder_plan_id)},
        )
    if isinstance(exc, ReminderSubjectAuthorityRequired):
        return status.HTTP_403_FORBIDDEN, ErrorBody(
            code="party_authority_required",
            message="the actor is not authorized to act for this Party",
            resolution=ErrorResolution.REQUEST_AUTHORITY,
            details={
                "party_id": str(exc.subject_party_id),
                "authority_anchor": "subject",
                "scope_key": exc.scope_key,
            },
        )
    if isinstance(exc, ReminderPlanRevisionConflict):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="revision_conflict",
            message="the aggregate changed since it was read",
            resolution=ErrorResolution.REFRESH_AND_RETRY,
            details={
                "aggregate_kind": "ReminderPlan",
                "aggregate_id": str(exc.reminder_plan_id),
                "expected_revision": exc.expected,
                "current_revision": exc.actual,
            },
        )
    if isinstance(exc, ReminderPlanNotActive):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="reminder_plan_not_active",
            message=str(exc),
            resolution=ErrorResolution.REFRESH_AND_RETRY,
            details={
                "reminder_plan_id": str(exc.reminder_plan_id),
                "status": exc.status,
            },
        )
    if isinstance(exc, DeliveryConfigurationError):
        return status.HTTP_422_UNPROCESSABLE_CONTENT, ErrorBody(
            code="invalid_channel_policy",
            message=exc.reason,
            resolution=ErrorResolution.FIX_REQUEST,
            details={"field": "channel_policy"},
        )
    return status.HTTP_500_INTERNAL_SERVER_ERROR, ErrorBody(
        code="communications_error",
        message="the communications command failed",
        resolution=ErrorResolution.OPERATOR_INTERVENTION,
    )
