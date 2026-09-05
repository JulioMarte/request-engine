from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast
from uuid import UUID

from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.booking.adapters.db.recovery_reschedule_mutation import (
    RecoveryMutationInputs,
)
from request_engine.modules.booking.adapters.db.recovery_reschedule_support import (
    lock_reservation_for_recovery,
)
from request_engine.modules.booking.adapters.db.recovery_reschedule_target import (
    prepare_target_mutation,
)
from request_engine.modules.booking.adapters.db.recovery_source_guards import (
    lock_recovery_locations,
)
from request_engine.modules.booking.adapters.db.reservation_commands import (
    ensure_reservation_revision,
    load_bookable_offering,
    validate_subject_location_and_origin,
)
from request_engine.modules.booking.adapters.db.subject_authority import (
    require_subject_authority,
)
from request_engine.modules.booking.application.authority import MANAGE_APPOINTMENT_SCOPE
from request_engine.modules.booking.application.errors import ReservationNotReschedulable
from request_engine.modules.booking.contracts.recovery import (
    RecoveryRescheduleRequest,
    RecoveryTargetUnavailable,
)
from request_engine.domain.policy import slot_step_minutes


@dataclass(frozen=True, slots=True)
class PreparedRecovery:
    reservation_row: RowMapping
    subject_party_id: UUID
    authority_details: dict[str, object]
    mutation: RecoveryMutationInputs


async def prepare_recovery(
    session: AsyncSession,
    *,
    request: RecoveryRescheduleRequest,
    start_at: datetime,
    source_observed_at: datetime,
    source_horizon_end: datetime,
) -> PreparedRecovery:
    row = await lock_reservation_for_recovery(
        session, request.organization_id, request.reservation_id
    )
    subject_party_id = cast(UUID, row["subject_party_id"])
    authority = await require_subject_authority(
        session,
        organization_id=request.organization_id,
        principal_id=request.principal_id,
        subject_party_id=subject_party_id,
        scope_key=MANAGE_APPOINTMENT_SCOPE,
        allow_operator_override=request.allow_subject_override,
    )
    ensure_reservation_revision(row, request.reservation_id, request.expected_revision)
    status = cast(str, row["status"])
    if status != "confirmed":
        raise ReservationNotReschedulable(request.reservation_id, status)
    if request.location_id is None or request.expected_target_location_operational_revision is None:
        raise RecoveryTargetUnavailable("recovery target requires Location provenance")
    duration_minutes = request.expected_planned_duration_minutes or 0
    if duration_minutes <= 0:
        raise RecoveryTargetUnavailable("recovery target requires planned duration")
    await lock_recovery_locations(
        session,
        organization_id=request.organization_id,
        source_location_id=request.source_location_id,
        expected_source_revision=request.expected_source_location_operational_revision,
        target_location_id=request.location_id,
        expected_target_revision=request.expected_target_location_operational_revision,
    )
    offering_id = cast(UUID, row["offering_version_id"])
    offering = await load_bookable_offering(session, request.organization_id, offering_id)
    base_duration_minutes = cast(int, offering["duration_minutes"])
    end_at = start_at + timedelta(minutes=duration_minutes)
    policy = cast(dict[str, object], row["booking_policy_snapshot"])
    step_minutes = slot_step_minutes(policy, base_duration_minutes)
    await validate_subject_location_and_origin(
        session,
        organization_id=request.organization_id,
        subject_party_id=subject_party_id,
        location_id=request.location_id,
        origin_request_id=cast(UUID | None, row["origin_request_id"]),
    )
    mutation = await prepare_target_mutation(
        session,
        request=request,
        offering_version_id=offering_id,
        start_at=start_at,
        end_at=end_at,
        duration_minutes=duration_minutes,
        base_duration_minutes=base_duration_minutes,
        step_minutes=step_minutes,
        source_observed_at=source_observed_at,
        source_horizon_end=source_horizon_end,
    )
    return PreparedRecovery(
        reservation_row=row,
        subject_party_id=subject_party_id,
        authority_details=authority.audit_details(),
        mutation=mutation,
    )
