from collections.abc import Mapping
from dataclasses import dataclass
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
)
from request_engine.modules.booking.contracts.recovery import RecoveryRescheduleRequest
from request_engine.modules.booking.domain.availability import (
    AvailabilityException,
    LiveCapacityClaim,
    RecurringAvailability,
)


@dataclass(frozen=True, slots=True)
class ContextualRecoveryAvailability:
    assignment_schedules: Mapping[UUID, tuple[RecurringAvailability, ...]]
    assignment_exceptions: Mapping[UUID, tuple[AvailabilityException, ...]]
    broad_exceptions: Mapping[UUID, tuple[AvailabilityException, ...]]
    live_claims: Mapping[UUID, tuple[LiveCapacityClaim, ...]]


async def load_contextual_recovery_availability(
    session: AsyncSession,
    *,
    request: RecoveryRescheduleRequest,
    resource_ids: tuple[UUID, ...],
    assignment_ids: tuple[UUID, ...],
    start_at: datetime,
    end_at: datetime,
) -> ContextualRecoveryAvailability:
    return ContextualRecoveryAvailability(
        assignment_schedules=await load_assignment_schedules(
            session, request.organization_id, assignment_ids
        ),
        assignment_exceptions=await load_assignment_exceptions(
            session, request.organization_id, assignment_ids, start_at, end_at
        ),
        broad_exceptions=await load_resource_exceptions(
            session, request.organization_id, resource_ids, start_at, end_at
        ),
        live_claims=await load_live_capacity_claims(
            session,
            request.organization_id,
            resource_ids,
            start_at,
            end_at,
            exclude_reservation_id=request.reservation_id,
        ),
    )
