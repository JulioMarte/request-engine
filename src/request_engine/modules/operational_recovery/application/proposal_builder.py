from datetime import timedelta
from uuid import UUID, uuid4

from request_engine.modules.booking.contracts.recovery import RecoveryBookingPort
from request_engine.modules.live_capacity.contracts.recovery import (
    RecoveryCapacityAssessment,
    RecoveryCommitmentFact,
)
from request_engine.modules.operational_recovery.application.fingerprints import (
    proposal_fingerprint,
)
from request_engine.modules.operational_recovery.application.proposal_checkpoint import (
    proposal_checkpoint,
)
from request_engine.modules.operational_recovery.application.proposal_policy import (
    choose_recovery_target,
    choose_replacement_target,
)
from request_engine.modules.operational_recovery.contracts.models import (
    AffectedReservation,
    RescheduleProposal,
)


async def build_proposal(
    *,
    organization_id: UUID,
    search_days: int,
    assessment: RecoveryCapacityAssessment,
    booking: RecoveryBookingPort,
) -> RescheduleProposal:
    affected = tuple(
        [
            await _build_affected(
                organization_id,
                search_days,
                assessment,
                booking,
                commitment,
            )
            for commitment in assessment.affected_commitments
        ]
    )
    checkpoint = proposal_checkpoint(assessment)
    fingerprint = proposal_fingerprint(
        source_fingerprint=assessment.source_fingerprint,
        source_checkpoint=checkpoint,
        service_queue_id=assessment.service_queue_id,
        resource_id=assessment.resource_id,
        location_id=assessment.location_id,
        executable_capacity_seconds=assessment.executable_capacity_seconds,
        committed_capacity_seconds=assessment.committed_capacity_seconds,
        shortfall_seconds=assessment.shortfall_seconds,
        affected=affected,
    )
    return RescheduleProposal(
        id=uuid4(),
        service_queue_id=assessment.service_queue_id,
        resource_id=assessment.resource_id,
        location_id=assessment.location_id,
        observed_at=assessment.observed_at,
        horizon_end=assessment.horizon_end,
        source_fingerprint=assessment.source_fingerprint,
        source_snapshot=assessment.source_snapshot,
        source_checkpoint=checkpoint,
        proposal_fingerprint=fingerprint,
        executable_capacity_seconds=assessment.executable_capacity_seconds,
        committed_capacity_seconds=assessment.committed_capacity_seconds,
        shortfall_seconds=assessment.shortfall_seconds,
        affected=affected,
        created_at=assessment.observed_at,
    )


async def _build_affected(
    organization_id: UUID,
    search_days: int,
    assessment: RecoveryCapacityAssessment,
    booking: RecoveryBookingPort,
    commitment: RecoveryCommitmentFact,
) -> AffectedReservation:
    slots = await booking.find_recovery_slots(
        organization_id=organization_id,
        offering_version_id=commitment.offering_version_id,
        window_start=max(assessment.observed_at, commitment.planned_starts_at),
        window_end=assessment.horizon_end + timedelta(days=search_days),
        location_id=assessment.location_id,
        limit=25,
    )
    target = choose_recovery_target(
        slots,
        original_start=commitment.planned_starts_at,
        original_end=commitment.planned_ends_at,
    )
    replacement_target = choose_replacement_target(
        slots,
        original_start=commitment.planned_starts_at,
        original_end=commitment.planned_ends_at,
        source_resource_id=assessment.resource_id,
    )
    return AffectedReservation(
        reservation_id=commitment.reservation_id,
        offering_version_id=commitment.offering_version_id,
        subject_party_id=commitment.subject_party_id,
        expected_revision=commitment.reservation_revision,
        original_start_at=commitment.planned_starts_at,
        original_end_at=commitment.planned_ends_at,
        target=target,
        replacement_target=replacement_target,
    )
