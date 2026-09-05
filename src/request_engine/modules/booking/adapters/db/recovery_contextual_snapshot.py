from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.booking.adapters.db.contextual_recovery_shared import (
    RequirementLike,
    load_resource_availability_revisions,
    lock_selected_assignments,
    require_expected_resource_revisions,
    resolve_selected_assignments,
)
from request_engine.modules.booking.adapters.db.contextual_supply import (
    AssignmentObservation,
    ContextTermObservation,
    LocationObservation,
    load_booking_terms,
    load_contextualization,
    load_location_observations,
)
from request_engine.modules.booking.adapters.db.recovery_contextual_availability import (
    ContextualRecoveryAvailability,
    load_contextual_recovery_availability,
)
from request_engine.modules.booking.adapters.db.reservation_commands import LockedResource
from request_engine.modules.booking.contracts.appointments import ResourceChoice
from request_engine.modules.booking.contracts.recovery import RecoveryRescheduleRequest
from request_engine.modules.booking.domain.contextual_supply import BaseBookingTerms


@dataclass(frozen=True, slots=True)
class ContextualRecoverySnapshot:
    ordered_requirement_ids: tuple[UUID, ...]
    selected_assignments: Mapping[UUID, AssignmentObservation]
    resource_revisions: Mapping[UUID, int]
    location: LocationObservation | None
    availability: ContextualRecoveryAvailability
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
    await lock_selected_assignments(
        session, organization_id=request.organization_id, choices=choices
    )
    resource_ids = tuple(sorted(resources, key=str))
    resource_revisions = await load_resource_availability_revisions(
        session, organization_id=request.organization_id, resource_ids=resource_ids
    )
    require_expected_resource_revisions(choices, resource_revisions)
    _, assignments = await load_contextualization(
        session, request.organization_id, resource_ids, start_at, end_at
    )
    selected = resolve_selected_assignments(
        choices=choices,
        requirements=requirements,
        assignments_by_resource=assignments,
        location_id=location_id,
        start_at=start_at,
        end_at=end_at,
    )
    assignment_ids = tuple(sorted({assignment.id for assignment in selected.values()}, key=str))
    availability = await load_contextual_recovery_availability(
        session,
        request=request,
        resource_ids=resource_ids,
        assignment_ids=assignment_ids,
        start_at=start_at,
        end_at=end_at,
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
    ordered_ids = tuple(
        row.id for row in sorted(requirements.values(), key=lambda item: item.ordinal)
    )
    return ContextualRecoverySnapshot(
        ordered_ids,
        selected,
        resource_revisions,
        locations.get(location_id),
        availability,
        base_terms,
        context_terms,
    )
