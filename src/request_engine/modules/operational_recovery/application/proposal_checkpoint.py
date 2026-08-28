from request_engine.modules.live_capacity.contracts.recovery import RecoveryCapacityAssessment
from request_engine.modules.operational_recovery.contracts.models import (
    RecoveryCommitmentCheckpoint,
    RecoverySourceCheckpoint,
)


def proposal_checkpoint(assessment: RecoveryCapacityAssessment) -> RecoverySourceCheckpoint:
    return RecoverySourceCheckpoint(
        projection_policy_revision=assessment.checkpoint.projection_policy_revision,
        resource_availability_revision=assessment.checkpoint.resource_availability_revision,
        location_operational_revision=assessment.checkpoint.location_operational_revision,
        recovery_source_revision=assessment.checkpoint.recovery_source_revision,
        commitments=tuple(
            RecoveryCommitmentCheckpoint(
                reservation_id=item.reservation_id,
                revision=item.revision,
                starts_at=item.starts_at,
                ends_at=item.ends_at,
            )
            for item in assessment.checkpoint.commitments
        ),
    )
