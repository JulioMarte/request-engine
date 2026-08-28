from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.booking.adapters.db.contextual_reservation_commands import (
    _load_resource_availability_revisions,
    _lock_selected_assignments,
    _require_expected_resource_revisions,
    _resolve_selected_assignments,
)
from request_engine.modules.booking.adapters.db.contextual_supply import (
    AssignmentObservation,
    ContextTermObservation,
    LocationObservation,
    load_assignment_exceptions,
    load_assignment_schedules,
    load_booking_terms,
    load_contextualization,
    load_location_observations,
)
from request_engine.modules.booking.adapters.db.resource_availability import (
    load_live_capacity_claims,
    load_resource_exceptions,
    load_resource_schedules,
)
from request_engine.modules.booking.adapters.db.reservation_commands import LockedResource
from request_engine.modules.booking.contracts.appointments import ResourceChoice
from request_engine.modules.booking.contracts.recovery import RecoveryRescheduleRequest
from request_engine.modules.booking.domain.availability import (
    AvailabilityException,
    LiveCapacityClaim,
    RecurringAvailability,
)
from request_engine.modules.booking.domain.contextual_supply import BaseBookingTerms


class RequirementLike(Protocol):
    id: UUID
    ordinal: int


@dataclass(frozen=True, slots=True)
class ContextualRecoverySnapshot:
    ordered_requirement_ids: tuple[UUID, ...]
    selected_assignments: Mapping[UUID, AssignmentObservation | None]
    resource_revisions: Mapping[UUID, int]
    location: LocationObservation | None
    assignment_schedules: Mapping[UUID, tuple[RecurringAvailability, ...]]
    assignment_exceptions: Mapping[UUID, tuple[AvailabilityException, ...]]
    broad_exceptions: Mapping[UUID, tuple[AvailabilityException, ...]]
    legacy_schedules: Mapping[UUID, tuple[RecurringAvailability, ...]]
    live_claims: Mapping[UUID, tuple[LiveCapacityClaim, ...]]
    base_terms: BaseBookingTerms
    context_terms: Mapping[UUID, tuple[ContextTermObservation, ...]]


async def load_contextual_recovery_snapshot(
    session: AsyncSession,
    *,
    request: RecoveryRescheduleRequest,
    offering_version_id: UUID,
    requirements: Mapping[UUID, RequirementLike],
    choices: dict[UUID, ResourceChoice],
    resources: dict[UUID, LockedResource],
    start_at: datetime,
    end_at: datetime,
    base_duration_minutes: int,
) -> ContextualRecoverySnapshot:
    location_id = request.location_id
    assert location_id is not None
    await _lock_selected_assignments(
        session, organization_id=request.organization_id, choices=choices
    )
    resource_ids = tuple(sorted(resources, key=str))
    resource_revisions = await _load_resource_availability_revisions(
        session, organization_id=request.organization_id, resource_ids=resource_ids
    )
    _require_expected_resource_revisions(choices, resource_revisions)
    contextualized, assignments = await load_contextualization(
        session, request.organization_id, resource_ids, start_at, end_at
    )
    selected = _resolve_selected_assignments(
        choices=choices,
        requirements=requirements,
        resources=resources,
        contextualized=contextualized,
        assignments_by_resource=assignments,
        location_id=location_id,
        start_at=start_at,
        end_at=end_at,
    )
    assignment_ids = tuple(sorted({a.id for a in selected.values() if a is not None}, key=str))
    legacy_ids = tuple(
        sorted(
            {choices[rid].resource_id for rid, assignment in selected.items() if assignment is None},
            key=str,
        )
    )
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
    locations = await load_location_observations(
        session, request.organization_id, (location_id,), start_at, end_at
    )
    base_terms, context_terms = await load_booking_terms(
        session,
        request.organization_id,
        offering_version_id,
        assignment_ids,
        base_duration_minutes,
        start_at,
        end_at,
    )
    return ContextualRecoverySnapshot(
        tuple(row.id for row in sorted(requirements.values(), key=lambda item: item.ordinal)),
        selected,
        resource_revisions,
        locations.get(location_id),
        assignment_schedules,
        assignment_exceptions,
        broad_exceptions,
        legacy_schedules,
        live_claims,
        base_terms,
        context_terms,
    )
