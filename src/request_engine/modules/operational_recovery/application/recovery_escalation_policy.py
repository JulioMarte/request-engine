from dataclasses import dataclass
from uuid import UUID

from request_engine.modules.operational_recovery.application.workflow_assessment import (
    RecoveryAssessmentDecision,
)
from request_engine.modules.operational_recovery.contracts.workflow import (
    RecoveryImpactKind,
    RecoveryIncident,
)

NEWLY_MATERIAL = "newly_material"
WORSENING_SEVERITY = "worsening_severity"


@dataclass(frozen=True, slots=True)
class RecoveryEscalationOutcome:
    operator_escalation_required: bool
    escalation_reason: str | None
    customer_impact_required: bool
    impact_recipient_party_ids: tuple[UUID, ...]


def evaluate_recovery_escalation_policy(
    *,
    decision: RecoveryAssessmentDecision,
    previous: RecoveryIncident | None,
    affected_subject_party_ids: tuple[UUID, ...],
) -> RecoveryEscalationOutcome:
    """Contract 32 section 5.6/13: durable escalation/communication policy outcome.

    Operator escalation is required when a material incident is newly opened or its
    severity worsens. Customer impact notification is requested only when specific
    commitments stopped being realistic; indeterminate truth never claims impact.
    """

    if decision.resolve:
        return RecoveryEscalationOutcome(False, None, False, ())
    if previous is None:
        reason: str | None = NEWLY_MATERIAL
    elif decision.escalation_level > previous.escalation_level:
        reason = WORSENING_SEVERITY
    else:
        reason = None
    notify = decision.impact_kind is not RecoveryImpactKind.INDETERMINATE and bool(
        affected_subject_party_ids
    )
    return RecoveryEscalationOutcome(
        operator_escalation_required=reason is not None,
        escalation_reason=reason,
        customer_impact_required=notify,
        impact_recipient_party_ids=affected_subject_party_ids if notify else (),
    )
