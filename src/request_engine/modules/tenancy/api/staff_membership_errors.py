from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from request_engine.modules.tenancy.application.errors import (
    StaffMembershipConflict,
    StaffMembershipError,
    StaffMembershipForbidden,
    StaffMembershipInputInvalid,
    StaffMembershipRevisionConflict,
)
from request_engine.platform.http.errors import ErrorBody, ErrorEnvelope, ErrorResolution


def add_staff_membership_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(StaffMembershipError, staff_membership_error_handler)


async def staff_membership_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, StaffMembershipError):
        raise exc
    status_code, body = _staff_membership_error(exc)
    return JSONResponse(
        status_code=status_code,
        content=ErrorEnvelope(error=body).model_dump(mode="json"),
    )


def _staff_membership_error(exc: StaffMembershipError) -> tuple[int, ErrorBody]:
    if isinstance(exc, StaffMembershipForbidden):
        return status.HTTP_403_FORBIDDEN, ErrorBody(
            code="staff_membership_forbidden",
            message="the current actor may not perform this staff lifecycle operation",
            resolution=ErrorResolution.REQUEST_AUTHORITY,
        )
    if isinstance(exc, StaffMembershipRevisionConflict):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="staff_membership_revision_conflict",
            message="staff state changed since the supplied revision",
            retryable=True,
            resolution=ErrorResolution.REFRESH_AND_RETRY,
        )
    if isinstance(exc, StaffMembershipConflict):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="staff_membership_conflict",
            message="the requested staff lifecycle change conflicts with current state",
            resolution=ErrorResolution.FIX_REQUEST,
        )
    if isinstance(exc, StaffMembershipInputInvalid):
        return status.HTTP_422_UNPROCESSABLE_CONTENT, ErrorBody(
            code="staff_membership_input_invalid",
            message="the requested staff lifecycle change violates a tenant invariant",
            resolution=ErrorResolution.FIX_REQUEST,
        )
    return status.HTTP_500_INTERNAL_SERVER_ERROR, ErrorBody(
        code="staff_membership_error",
        message="the staff lifecycle command failed",
        resolution=ErrorResolution.OPERATOR_INTERVENTION,
    )
