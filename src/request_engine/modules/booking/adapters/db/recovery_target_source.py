from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.booking.adapters.db.recovery_source_guards import (
    require_current_recovery_window,
    require_source_commitments,
    require_source_resource_revision,
)
from request_engine.modules.booking.contracts.recovery import RecoveryRescheduleRequest


async def validate_recovery_source_checkpoint(
    session: AsyncSession,
    *,
    request: RecoveryRescheduleRequest,
    target_start_at: datetime,
    source_observed_at: datetime,
    source_horizon_end: datetime,
) -> None:
    await require_source_resource_revision(
        session,
        organization_id=request.organization_id,
        resource_id=request.source_resource_id,
        expected_revision=request.expected_source_resource_availability_revision,
    )
    await require_source_commitments(
        session,
        organization_id=request.organization_id,
        resource_id=request.source_resource_id,
        location_id=request.source_location_id,
        observed_at=source_observed_at,
        horizon_end=source_horizon_end,
        expected=request.expected_source_commitments,
    )
    await require_current_recovery_window(
        session,
        target_start_at=target_start_at,
        source_horizon_end=source_horizon_end,
    )
