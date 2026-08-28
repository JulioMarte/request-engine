from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.booking.adapters.db.contextual_reservation_commands import (
    _build_authoritative_profiles,
    _configuration_fingerprint,
    _effective_context_observations,
    _load_resource_availability_revisions,
    _lock_selected_assignments,
    _require_expected_resource_revisions,
    _resolve_selected_assignments,
)
from request_engine.modules.booking.adapters.db.contextual_supply import (
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
from request_engine.modules.booking.domain.contextual_supply import (
    ConflictingContextualTerms,
    ContextNotBookable,
    MissingCommercialTerms,
    resolve_booking_terms,
)


async def validate_contextual_recovery_target(
    session: AsyncSession,
    *,
    request: RecoveryRescheduleRequest,
    offering_version_id: UUID,
    requirements: dict[UUID, object],
    choices: dict[UUID, ResourceChoice],
    resources: dict[UUID, LockedResource],
    start_at: datetime,
    end_at: datetime,
    base_duration_minutes: int,
    step_minutes: int,
) -> None:
    location_id = request.location_id
    expected_location_revision = request.expected_target_location_operational_revision
    expected_duration = request.expected_planned_duration_minutes
    if location_id is None or expected_location_revision is None:
        raise RecoveryTargetUnavailable("contextual recovery target requires Location provenance")
    if expected_duration is None or expected_duration <= 0:
        raise RecoveryTargetUnavailable("contextual recovery target requires planned duration")
    if request.expected_amount is None or request.expected_currency is None:
        raise RecoveryTargetUnavailable("contextual recovery target requires commercial provenance")
    if not request.expected_configuration_fingerprint:
        raise RecoveryTargetUnavailable("contextual recovery target requires configuration fingerprint")

    await _lock_selected_assignments(
        session,
        organization_id=request.organization_id,
        choices=choices,
    )
    resource_revisions = await _load_resource_availability_revisions(
        session,
        organization_id=request.organization_id,
        resource_ids=tuple(sorted(resources, key=str)),
    )
    _require_expected_resource_revisions(choices, resource_revisions)
    contextualized, assignments_by_resource = await load_contextualization(
        session,
        request.organization_id,
        tuple(sorted(resources, key=str)),
        start_at,
        end_at,
    )
    typed_requirements = cast(dict[UUID, object], requirements)
    selected = _resolve_selected_assignments(  # type: ignore[arg-type]
        choices=choices,
        requirements=typed_requirements,
        resources=resources,
        contextualized=contextualized,
        assignments_by_resource=assignments_by_resource,
        location_id=location_id,
        start_at=start_at,
        end_at=end_at,
    )
    assignment_ids = tuple(
        sorted({row.id for row in selected.values() if row is not None}, key=str)
    )
    legacy_ids = tuple(
        sorted(
            {
                choices[requirement_id].resource_id
                for requirement_id, assignment in selected.items()
                if assignment is None
            },
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
        session, request.organization_id, tuple(sorted(resources, key=str)), start_at, end_at
    )
    legacy_schedules = await load_resource_schedules(
        session, request.organization_id, legacy_ids
    )
    live_claims = await load_live_capacity_claims(
        session,
        request.organization_id,
        tuple(sorted(resources, key=str)),
        start_at,
        end_at,
        exclude_reservation_id=request.reservation_id,
    )
    locations = await load_location_observations(
        session, request.organization_id, (location_id,), start_at, end_at
    )
    location = locations.get(location_id)
    if location is None or location.operational_revision != expected_location_revision:
        raise RecoveryTargetUnavailable("target Location operational configuration changed")
    if not interval_is_scheduled_available(location.profile, start_at=start_at, end_at=end_at):
        raise RecoveryTargetUnavailable("target Location is not operationally available")

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
        row.id for row in sorted(requirements.values(), key=lambda item: item.ordinal)  # type: ignore[attr-defined]
    )
    observations = _effective_context_observations(
        ordered_ids, selected, context_terms, start_at
    )
    try:
        resolved = resolve_booking_terms(base_terms, observations)
    except (MissingCommercialTerms, ConflictingContextualTerms, ContextNotBookable) as exc:
        raise RecoveryTargetUnavailable("contextual commercial terms changed") from exc
    if (
        resolved.amount != request.expected_amount
        or resolved.currency != request.expected_currency
        or resolved.planned_duration_minutes != expected_duration
    ):
        raise RecoveryTargetUnavailable("contextual commercial commitment changed")

    profiles = _build_authoritative_profiles(
        ordered_requirement_ids=ordered_ids,
        choices=choices,
        selected_assignments=selected,
        resources=resources,
        location=location,
        assignment_schedules=assignment_schedules,
        assignment_exceptions=assignment_exceptions,
        broad_exceptions=broad_exceptions,
        legacy_schedules=legacy_schedules,
        live_claims=live_claims,
    )
    revalidate_exact_slot(
        requirements=requirements,  # type: ignore[arg-type]
        choices=choices,
        profiles=profiles,
        start_at=start_at,
        end_at=end_at,
        duration_minutes=resolved.planned_duration_minutes,
        step_minutes=step_minutes,
    )
    fingerprint = _configuration_fingerprint(
        offering_version_id=offering_version_id,
        location=location,
        ordered_requirement_ids=ordered_ids,
        choices=choices,
        resources=resources,
        current_availability_revisions=resource_revisions,
        selected_assignments=selected,
        base_terms=base_terms,
        context_observations=observations,
        resolved=resolved,
    )
    if fingerprint != request.expected_configuration_fingerprint:
        raise RecoveryTargetUnavailable("contextual configuration fingerprint changed")
