from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast
from uuid import UUID

from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.booking.adapters.db.recovery_availability import load_recovery_profiles_excluding_reservation
from request_engine.modules.booking.adapters.db.recovery_reschedule_mutation import RecoveryMutationInputs
from request_engine.modules.booking.adapters.db.recovery_reschedule_support import load_active_recovery_claims, lock_reservation_for_recovery, source_claims_are_contextual
from request_engine.modules.booking.adapters.db.recovery_source_guards import lock_recovery_locations, require_current_recovery_window, require_source_commitments, require_source_resource_revision
from request_engine.modules.booking.adapters.db.reservation_commands import ensure_reservation_revision, load_bookable_offering, load_requirements, lock_resources, revalidate_exact_slot, validate_choice_cardinality, validate_resource_capabilities, validate_subject_location_and_origin
from request_engine.modules.booking.adapters.db.subject_authority import require_subject_authority
from request_engine.modules.booking.application.authority import MANAGE_APPOINTMENT_SCOPE
from request_engine.modules.booking.application.errors import ReservationNotReschedulable
from request_engine.modules.booking.contracts.recovery import RecoveryBookingConflict, RecoveryRescheduleRequest, RecoveryTargetUnavailable
from request_engine.modules.booking.domain.policy import slot_step_minutes


@dataclass(frozen=True, slots=True)
class PreparedRecovery:
    reservation_row: RowMapping
    subject_party_id: UUID
    authority_details: dict[str, object]
    mutation: RecoveryMutationInputs


async def prepare_recovery(session: AsyncSession, *, request: RecoveryRescheduleRequest, start_at: datetime, source_observed_at: datetime, source_horizon_end: datetime) -> PreparedRecovery:
    reservation_row = await lock_reservation_for_recovery(session, request.organization_id, request.reservation_id)
    subject_party_id = cast(UUID, reservation_row["subject_party_id"])
    authority = await require_subject_authority(session, organization_id=request.organization_id, principal_id=request.principal_id, subject_party_id=subject_party_id, scope_key=MANAGE_APPOINTMENT_SCOPE, allow_operator_override=request.allow_subject_override)
    ensure_reservation_revision(reservation_row, request.reservation_id, request.expected_revision)
    status = cast(str, reservation_row["status"])
    if status != "confirmed":
        raise ReservationNotReschedulable(request.reservation_id, status)
    await lock_recovery_locations(session, organization_id=request.organization_id, source_location_id=request.source_location_id, expected_source_revision=request.expected_source_location_operational_revision, target_location_id=request.location_id)
    offering_version_id = cast(UUID, reservation_row["offering_version_id"])
    offering = await load_bookable_offering(session, request.organization_id, offering_version_id)
    duration_minutes = cast(int, offering["duration_minutes"])
    end_at = start_at + timedelta(minutes=duration_minutes)
    step_minutes = slot_step_minutes(cast(dict[str, object], reservation_row["booking_policy_snapshot"]), duration_minutes)
    await validate_subject_location_and_origin(session, organization_id=request.organization_id, subject_party_id=subject_party_id, location_id=request.location_id, origin_request_id=cast(UUID | None, reservation_row["origin_request_id"]))
    requirements = await load_requirements(session, request.organization_id, offering_version_id)
    choices = validate_choice_cardinality(requirements, request.resources)
    old_claims = await load_active_recovery_claims(session, request.organization_id, request.reservation_id)
    if source_claims_are_contextual(old_claims):
        raise RecoveryTargetUnavailable("contextual source Reservation cannot be recovery-rescheduled yet")
    old_resource_ids = tuple(cast(UUID, row["resource_id"]) for row in old_claims)
    if request.source_resource_id not in old_resource_ids:
        raise RecoveryBookingConflict("recovery source Resource is no longer an active Reservation commitment")
    new_resource_ids = tuple(choice.resource_id for choice in choices.values())
    resources = await lock_resources(session, organization_id=request.organization_id, resource_ids=tuple(sorted(set(old_resource_ids + new_resource_ids), key=str)))
    await require_source_resource_revision(session, organization_id=request.organization_id, resource_id=request.source_resource_id, expected_revision=request.expected_source_resource_availability_revision)
    await require_source_commitments(session, organization_id=request.organization_id, resource_id=request.source_resource_id, location_id=request.source_location_id, observed_at=source_observed_at, horizon_end=source_horizon_end, expected=request.expected_source_commitments)
    await require_current_recovery_window(session, target_start_at=start_at, source_horizon_end=source_horizon_end)
    selected_resources = {resource_id: resources[resource_id] for resource_id in set(new_resource_ids)}
    await validate_resource_capabilities(session, organization_id=request.organization_id, requirements=requirements, choices=choices, resources=selected_resources, location_id=request.location_id)
    profiles = await load_recovery_profiles_excluding_reservation(session, organization_id=request.organization_id, resources=selected_resources, start_at=start_at, end_at=end_at, reservation_id=request.reservation_id)
    revalidate_exact_slot(requirements=requirements, choices=choices, profiles=profiles, start_at=start_at, end_at=end_at, duration_minutes=duration_minutes, step_minutes=step_minutes)
    mutation = RecoveryMutationInputs(requirements=requirements, choices=choices, old_claims=old_claims, start_at=start_at, end_at=end_at)
    return PreparedRecovery(reservation_row=reservation_row, subject_party_id=subject_party_id, authority_details=authority.audit_details(), mutation=mutation)
