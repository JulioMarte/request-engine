from uuid import UUID

from request_engine.modules.booking.contracts.recovery import (
    RecoveryCommitmentCheckpoint as BookingCommitmentCheckpoint,
)
from request_engine.modules.booking.contracts.recovery import RecoveryRescheduleRequest
from request_engine.modules.operational_recovery.contracts.models import (
    AffectedReservation,
    RecoveryTarget,
    RescheduleProposal,
)


def workflow_booking_request(
    *,
    organization_id: UUID,
    principal_id: UUID,
    idempotency_key: str,
    allow_subject_override: bool,
    proposal: RescheduleProposal,
    affected: AffectedReservation,
    target: RecoveryTarget | None = None,
) -> RecoveryRescheduleRequest:
    selected = target if target is not None else affected.target
    if selected is None:
        raise RuntimeError("actionable recovery target is missing")
    return RecoveryRescheduleRequest(
        organization_id=organization_id,
        principal_id=principal_id,
        reservation_id=affected.reservation_id,
        expected_revision=affected.expected_revision,
        start_at=selected.start_at,
        location_id=selected.location_id,
        resources=selected.resources,
        source_service_queue_id=proposal.service_queue_id,
        expected_recovery_source_revision=proposal.source_checkpoint.recovery_source_revision,
        source_resource_id=proposal.resource_id,
        expected_source_resource_availability_revision=(
            proposal.source_checkpoint.resource_availability_revision
        ),
        source_location_id=proposal.location_id,
        expected_source_location_operational_revision=(
            proposal.source_checkpoint.location_operational_revision
        ),
        source_observed_at=proposal.observed_at,
        source_horizon_end=proposal.horizon_end,
        expected_source_commitments=tuple(
            BookingCommitmentCheckpoint(
                reservation_id=item.reservation_id,
                revision=item.revision,
                starts_at=item.starts_at,
                ends_at=item.ends_at,
            )
            for item in proposal.source_checkpoint.commitments
        ),
        idempotency_key=idempotency_key,
        allow_subject_override=allow_subject_override,
        expected_planned_duration_minutes=selected.planned_duration_minutes,
        expected_amount=selected.amount,
        expected_currency=selected.currency,
        expected_target_location_operational_revision=selected.location_operational_revision,
        expected_configuration_fingerprint=selected.configuration_fingerprint,
    )
