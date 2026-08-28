import json
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.live_capacity.contracts.recovery import (
    RecoveryCapacityAssessment,
)
from request_engine.modules.operational_recovery.application.recovery_escalation_policy import (
    RecoveryEscalationOutcome,
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
