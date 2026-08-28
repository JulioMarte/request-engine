from uuid import UUID

from request_engine.modules.operational_recovery.application.workflow_assessment import (
    RecoveryAssessmentDecision,
)
from request_engine.modules.operational_recovery.contracts.workflow import RecoveryIncident


def incident_matches_assessment(
    incident: RecoveryIncident,
    *,
    source_revision: int,
    source_fingerprint: str,
    proposal_id: UUID | None,
    decision: RecoveryAssessmentDecision,
) -> bool:
    return (
        not decision.resolve
        and incident.source_revision == source_revision
        and incident.source_fingerprint == source_fingerprint
        and incident.current_proposal_id == proposal_id
        and incident.impact_kind == decision.impact_kind
        and incident.escalation_level == decision.escalation_level
    )
