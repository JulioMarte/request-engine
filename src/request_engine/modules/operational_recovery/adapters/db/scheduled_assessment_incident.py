from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.live_capacity.contracts.recovery import RecoveryCapacityAssessment
from request_engine.modules.operational_recovery.adapters.db.workflow_incident_write import (
    insert_incident,
    update_incident,
)
from request_engine.modules.operational_recovery.application.workflow_assessment import (
    RecoveryAssessmentDecision,
)
from request_engine.modules.operational_recovery.contracts.workflow import RecoveryIncident


async def upsert_incident_from_assessment(
    session: AsyncSession,
    *,
    organization_id: UUID,
    service_queue_id: UUID,
    existing: RecoveryIncident | None,
    assessment: RecoveryCapacityAssessment,
    decision: RecoveryAssessmentDecision,
    source_revision: int,
    proposal_id: UUID | None,
) -> RecoveryIncident:
    if existing is None:
        return await insert_incident(
            session,
            organization_id=organization_id,
            service_queue_id=service_queue_id,
            resource_id=assessment.resource_id,
            location_id=assessment.location_id,
            source_revision=source_revision,
            source_fingerprint=assessment.source_fingerprint,
            impact_kind=decision.impact_kind,
            escalation_level=decision.escalation_level,
            current_proposal_id=proposal_id,
        )
    return await update_incident(
        session,
        organization_id=organization_id,
        incident_id=existing.id,
        source_revision=source_revision,
        source_fingerprint=assessment.source_fingerprint,
        impact_kind=decision.impact_kind,
        escalation_level=decision.escalation_level,
        current_proposal_id=proposal_id,
        resolve=decision.resolve,
    )
