from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.live_capacity.contracts.recovery import RecoveryCapacityAssessment
from request_engine.modules.operational_recovery.adapters.db.workflow_incident_write import (
    insert_incident,
    update_incident,
)
from request_engine.modules.operational_recovery.application.recovery_escalation_policy import (
    RecoveryEscalationOutcome,
    evaluate_recovery_escalation_policy,
)
from request_engine.modules.operational_recovery.application.workflow_assessment import (
    RecoveryAssessmentDecision,
)
from request_engine.modules.operational_recovery.contracts.workflow import RecoveryIncident

from .scheduled_assessment_escalation import record_escalation_outcome


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
) -> tuple[RecoveryIncident, RecoveryEscalationOutcome]:
    if existing is None:
        incident = await insert_incident(
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
    else:
        incident = await update_incident(
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
    outcome = evaluate_recovery_escalation_policy(
        decision=decision,
        previous=existing,
        affected_subject_party_ids=tuple(
            dict.fromkeys(fact.subject_party_id for fact in assessment.affected_commitments)
        ),
    )
    await record_escalation_outcome(
        session,
        organization_id=organization_id,
        incident_id=incident.id,
        assessment=assessment,
        escalation_level=decision.escalation_level,
        outcome=outcome,
    )
    return incident, outcome
