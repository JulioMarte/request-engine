from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.booking.adapters.db.contextual_supply import (
    load_assignment_exceptions,
    load_assignment_schedules,
)
from request_engine.modules.booking.adapters.db.resource_availability import (
    load_live_capacity_claims,
    load_resource_exceptions,
    load_resource_schedules,
)
from request_engine.modules.booking.contracts.recovery import RecoveryRescheduleRequest


async def load_contextual_recovery_availability(
    session: AsyncSession,
    *,
    request: RecoveryRescheduleRequest,
    resource_ids: tuple[UUID, ...],
    assignment_ids: tuple[UUID, ...],
    legacy_ids: tuple[UUID, ...],
    start_at: datetime,
    end_at: datetime,
) -> tuple[object, object, object, object, object]:
    assignment_schedules = await load_assignment_schedules(
        session, request.organization_id, assignment_ids
    )
    assignment_exceptions = await load_assignment_exceptions(
        session, request.organization_id, assignment_ids, start_at, end_at
    )
    broad_exceptions = await load_resource_exceptions(
        session, request.organization_id, resource_ids, start_at, end_at
    )
    legacy_schedules = await load_resource_schedules(
        session, request.organization_id, legacy_ids
    )
    live_claims = await load_live_capacity_claims(
        session,
        request.organization_id,
        resource_ids,
        start_at,
        end_at,
        exclude_reservation_id=request.reservation_id,
    )
    return (
        assignment_schedules,
        assignment_exceptions,
        broad_exceptions,
        legacy_schedules,
        live_claims,
    )
