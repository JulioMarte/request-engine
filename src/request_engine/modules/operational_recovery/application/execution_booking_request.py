from request_engine.modules.booking.contracts.recovery import (
    RecoveryCommitmentCheckpoint as BookingCommitmentCheckpoint,
)
from request_engine.modules.booking.contracts.recovery import RecoveryRescheduleRequest
from request_engine.modules.operational_recovery.application.commands import ExecuteRecoveryCommand
from request_engine.modules.operational_recovery.contracts.models import (
    AffectedReservation,
    RecoveryExecution,
    RescheduleProposal,
)


def booking_request(
    command: ExecuteRecoveryCommand,
    proposal: RescheduleProposal,
    affected: AffectedReservation,
    execution: RecoveryExecution,
) -> RecoveryRescheduleRequest:
    target = affected.target
    if target is None:
        raise RuntimeError("prepared recovery execution is missing target")
    return RecoveryRescheduleRequest(
        organization_id=command.organization_id,
        principal_id=command.principal_id,
        reservation_id=command.reservation_id,
        expected_revision=affected.expected_revision,
        start_at=target.start_at,
        location_id=target.location_id,
        resources=target.resources,
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
        idempotency_key=f"recovery:{execution.id}:booking:v1",
        allow_subject_override=command.allow_subject_override,
        expected_planned_duration_minutes=target.planned_duration_minutes,
        expected_amount=target.amount,
        expected_currency=target.currency,
        expected_target_location_operational_revision=target.location_operational_revision,
        expected_configuration_fingerprint=target.configuration_fingerprint,
    )
