from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.live_capacity.contracts.recovery import RecoveryCapacityAssessment
from request_engine.modules.operational_recovery.adapters.db.automatic_proposal_store import (
    insert_automatic_proposal,
)
from request_engine.modules.operational_recovery.application.workflow_assessment import (
    RecoveryAssessmentDecision,
)
from request_engine.modules.operational_recovery.contracts.models import RescheduleProposal


async def automatic_proposal_for_assessment(
    session: AsyncSession,
    *,
    organization_id: UUID,
    service_queue_id: UUID,
    source_revision: int,
    assessment: RecoveryCapacityAssessment,
    decision: RecoveryAssessmentDecision,
    proposal: RescheduleProposal | None,
) -> UUID | None:
    if not decision.material or assessment.shortfall_seconds <= 0:
        return None
    if proposal is None:
        raise ValueError("material shortfall assessment requires a proposal")
    if (
        proposal.service_queue_id != service_queue_id
        or proposal.source_fingerprint != assessment.source_fingerprint
        or proposal.source_checkpoint.recovery_source_revision != source_revision
    ):
        raise ValueError("automatic recovery proposal does not match assessment")
    return await insert_automatic_proposal(
        session,
        organization_id=organization_id,
        source_revision=source_revision,
        proposal=proposal,
    )
