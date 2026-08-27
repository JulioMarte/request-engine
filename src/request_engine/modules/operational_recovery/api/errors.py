from fastapi import Request, status
from fastapi.responses import JSONResponse

from request_engine.modules.operational_recovery.application.errors import (
    OperationalRecoveryError,
    RecoveryIdempotencyConflict,
    RecoveryProposalNotFound,
    RecoveryReservationNotAffected,
    RecoveryShortfallNotMaterial,
    RecoveryTargetUnavailable,
    StaleRecoveryProposal,
)
from request_engine.platform.http.errors import ErrorBody, ErrorEnvelope, ErrorResolution


async def operational_recovery_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, OperationalRecoveryError):
        raise exc
    status_code, body = _map_error(exc)
    return JSONResponse(
        status_code=status_code,
        content=ErrorEnvelope(error=body).model_dump(mode="json"),
    )


def _map_error(exc: OperationalRecoveryError) -> tuple[int, ErrorBody]:
    if isinstance(exc, StaleRecoveryProposal):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="STALE_RECOVERY_PROPOSAL",
            message="the recovery proposal no longer matches authoritative operational state",
            resolution=ErrorResolution.REFRESH_AND_RETRY,
        )
    if isinstance(exc, RecoveryIdempotencyConflict):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="RECOVERY_IDEMPOTENCY_CONFLICT",
            message="the recovery execution identity was already used for a different command",
            resolution=ErrorResolution.REFRESH_AND_RETRY,
        )
    if isinstance(exc, RecoveryShortfallNotMaterial):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="RECOVERY_SHORTFALL_NOT_MATERIAL",
            message="no positive material recovery shortfall exists for this context",
            resolution=ErrorResolution.REFRESH_AND_RETRY,
        )
    if isinstance(exc, RecoveryReservationNotAffected):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="RECOVERY_RESERVATION_NOT_AFFECTED",
            message="the Reservation is not part of this recovery proposal",
            resolution=ErrorResolution.FIX_REQUEST,
            details={"reservation_id": str(exc.reservation_id)},
        )
    if isinstance(exc, RecoveryTargetUnavailable):
        return status.HTTP_409_CONFLICT, ErrorBody(
            code="RECOVERY_TARGET_UNAVAILABLE",
            message=exc.reason or "the proposed recovery target is not currently executable",
            resolution=ErrorResolution.REFRESH_AND_RETRY,
            details={"reservation_id": str(exc.reservation_id)},
        )
    if isinstance(exc, RecoveryProposalNotFound):
        return status.HTTP_404_NOT_FOUND, ErrorBody(
            code="recovery_proposal_not_found",
            message="the requested recovery proposal was not found",
            resolution=ErrorResolution.FIX_REQUEST,
            details={"proposal_id": str(exc.proposal_id)},
        )
    return status.HTTP_500_INTERNAL_SERVER_ERROR, ErrorBody(
        code="operational_recovery_error",
        message="the operational recovery operation failed",
        resolution=ErrorResolution.OPERATOR_INTERVENTION,
    )
