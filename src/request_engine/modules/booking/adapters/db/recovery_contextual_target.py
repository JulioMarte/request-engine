from collections.abc import Mapping
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.booking.adapters.db.contextual_recovery_shared import (
    RequirementLike,
    build_authoritative_profiles,
    configuration_fingerprint,
)
from request_engine.modules.booking.adapters.db.recovery_contextual_snapshot import (
    load_contextual_recovery_snapshot,
)
from request_engine.modules.booking.adapters.db.recovery_contextual_terms import (
    resolve_recovery_terms,
)
from request_engine.modules.booking.adapters.db.reservation_commands import (
    LockedResource,
    revalidate_exact_slot,
)
from request_engine.modules.booking.contracts.appointments import ResourceChoice
from request_engine.modules.booking.contracts.recovery import (
    RecoveryRescheduleRequest,
    RecoveryTargetUnavailable,
)
from request_engine.modules.booking.domain.availability import interval_is_scheduled_available


def contextual_target_requested(request: RecoveryRescheduleRequest) -> bool:
    return any(choice.resource_location_assignment_id is not None for choice in request.resources)


async def validate_contextual_recovery_target(
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
    step_minutes: int,
    source_contextual: bool,
) -> None:
    expected_location_revision = request.expected_target_location_operational_revision
    expected_duration = request.expected_planned_duration_minutes
    if request.location_id is None or expected_location_revision is None:
        raise RecoveryTargetUnavailable("contextual recovery target requires Location provenance")
    if expected_duration is None or expected_duration <= 0:
        raise RecoveryTargetUnavailable("contextual recovery target requires planned duration")
    if request.expected_amount is None or request.expected_currency is None:
        raise RecoveryTargetUnavailable("contextual recovery target requires commercial provenance")
    if not request.expected_configuration_fingerprint:
        raise RecoveryTargetUnavailable(
            "contextual recovery target requires configuration fingerprint"
        )
    snapshot = await load_contextual_recovery_snapshot(
        session,
        request=request,
        offering_version_id=offering_version_id,
        requirements=requirements,
        choices=choices,
        resources=resources,
        start_at=start_at,
        end_at=end_at,
        base_duration_minutes=base_duration_minutes,
    )
    location = snapshot.location
    if location is None or location.operational_revision != expected_location_revision:
        raise RecoveryTargetUnavailable("target Location operational configuration changed")
    if not interval_is_scheduled_available(location.profile, start_at=start_at, end_at=end_at):
        raise RecoveryTargetUnavailable("target Location is not operationally available")
    resolved, observations = await resolve_recovery_terms(
        session,
        request=request,
        snapshot=snapshot,
        start_at=start_at,
        source_contextual=source_contextual,
    )
    availability = snapshot.availability
    profiles = build_authoritative_profiles(
        ordered_requirement_ids=snapshot.ordered_requirement_ids,
        choices=choices,
        selected_assignments=snapshot.selected_assignments,
        resources=resources,
        location=location,
        assignment_schedules=availability.assignment_schedules,
        assignment_exceptions=availability.assignment_exceptions,
        broad_exceptions=availability.broad_exceptions,
        live_claims=availability.live_claims,
    )
    revalidate_exact_slot(
        requirements=cast(Any, requirements),
        choices=choices,
        profiles=profiles,
        start_at=start_at,
        end_at=end_at,
        duration_minutes=resolved.planned_duration_minutes,
        step_minutes=step_minutes,
    )
    fingerprint = configuration_fingerprint(
        offering_version_id=offering_version_id,
        location=location,
        ordered_requirement_ids=snapshot.ordered_requirement_ids,
        choices=choices,
        resources=resources,
        current_availability_revisions=snapshot.resource_revisions,
        selected_assignments=snapshot.selected_assignments,
        base_terms=snapshot.base_terms,
        context_observations=observations,
        resolved=resolved,
    )
    if fingerprint != request.expected_configuration_fingerprint:
        raise RecoveryTargetUnavailable("contextual configuration fingerprint changed")
