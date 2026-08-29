import json
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.live_capacity.contracts.recovery import (
    RecoveryCapacityAssessment,
)
from request_engine.modules.operational_recovery.application.recovery_escalation_policy import (
    RecoveryEscalationOutcome,
    evaluate_recovery_escalation_policy,
)
from request_engine.modules.operational_recovery.application.workflow_assessment import (
    RecoveryAssessmentDecision,
)

_INSERT = text(
    """
    INSERT INTO request_engine.operational_recovery_escalations (
      organization_id, incident_id, source_revision, escalation_level,
      operator_escalation_required, escalation_reason,
      customer_impact_required, impact_recipient_party_ids, source_fingerprint
    ) VALUES (
      :organization_id, :incident_id, :source_revision, :escalation_level,
      :operator_escalation_required, :escalation_reason,
      :customer_impact_required, cast(:impact_recipient_party_ids AS jsonb),
      :source_fingerprint
    )
    """
)


async def record_escalation_outcome(
    session: AsyncSession,
    *,
    organization_id: UUID,
    incident_id: UUID,
    assessment: RecoveryCapacityAssessment,
    escalation_level: int,
    outcome: RecoveryEscalationOutcome,
) -> None:
    await session.execute(
        _INSERT,
        {
            "organization_id": organization_id,
            "incident_id": incident_id,
            "source_revision": assessment.checkpoint.recovery_source_revision,
            "escalation_level": escalation_level,
            "operator_escalation_required": outcome.operator_escalation_required,
            "escalation_reason": outcome.escalation_reason,
            "customer_impact_required": outcome.customer_impact_required,
            "impact_recipient_party_ids": json.dumps(
                [str(party_id) for party_id in outcome.impact_recipient_party_ids]
            ),
            "source_fingerprint": assessment.source_fingerprint,
        },
    )


_RESOLVED_WITHOUT_CLEARED_OUTCOME = text(
    """
    SELECT i.id
    FROM request_engine.operational_recovery_incidents i
    WHERE i.organization_id = :organization_id
      AND i.service_queue_id = :service_queue_id
      AND i.status = 'resolved'
      AND NOT EXISTS (
          SELECT 1
          FROM request_engine.operational_recovery_escalations e
          WHERE e.organization_id = i.organization_id
            AND e.incident_id = i.id
            AND e.operator_escalation_required = false
            AND e.customer_impact_required = false
      )
    ORDER BY i.id DESC
    LIMIT 1
    """
)


async def record_healthy_scope_closure(
    session: AsyncSession,
    *,
    organization_id: UUID,
    service_queue_id: UUID,
    assessment: RecoveryCapacityAssessment,
    decision: RecoveryAssessmentDecision,
) -> RecoveryEscalationOutcome | None:
    """Close the escalation ledger of an incident an operator action already resolved.

    Action-driven reprojection advances incident truth without recording an
    escalation outcome (document 33 disposition). The material source change the
    action causes schedules one fresh deduped reassessment; when that assessment is
    healthy this records the resolving outcome for the new revision exactly once.
    """

    if not decision.resolve:
        return None
    row = (
        await session.execute(
            _RESOLVED_WITHOUT_CLEARED_OUTCOME,
            {"organization_id": organization_id, "service_queue_id": service_queue_id},
        )
    ).first()
    if row is None:
        return None
    outcome = evaluate_recovery_escalation_policy(
        decision=decision,
        previous=None,
        affected_subject_party_ids=(),
    )
    await record_escalation_outcome(
        session,
        organization_id=organization_id,
        incident_id=row[0],
        assessment=assessment,
        escalation_level=decision.escalation_level,
        outcome=outcome,
    )
    return outcome
