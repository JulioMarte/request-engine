from dataclasses import dataclass
from uuid import UUID

from request_engine.modules.live_capacity.contracts.projection import ProjectionState
from request_engine.modules.live_capacity.contracts.recovery import (
    RecoveryCapacityAssessment,
    RecoveryCapacitySource,
)
from request_engine.modules.operational_recovery.application.workflow_ports import (
    RecoveryWorkflowRepository,
)
from request_engine.modules.operational_recovery.contracts.workflow import (
    RecoveryImpactKind,
    RecoveryIncident,
)


@dataclass(frozen=True, slots=True)
class RecoveryAssessmentDecision:
    material: bool
    resolve: bool
    impact_kind: RecoveryImpactKind
    escalation_level: int


def classify_recovery_assessment(
    assessment: RecoveryCapacityAssessment,
) -> RecoveryAssessmentDecision:
    if assessment.projection_state is ProjectionState.INDETERMINATE:
        return RecoveryAssessmentDecision(
            material=True,
            resolve=False,
            impact_kind=RecoveryImpactKind.INDETERMINATE,
            escalation_level=3,
        )
    if assessment.scheduled_shortfall_seconds > 0 or assessment.affected_commitments:
        return RecoveryAssessmentDecision(
            material=True,
            resolve=False,
            impact_kind=RecoveryImpactKind.CAPACITY_SHORTFALL,
            escalation_level=2,
        )
    if assessment.live_shortfall_seconds > 0:
        return RecoveryAssessmentDecision(
            material=True,
            resolve=False,
            impact_kind=RecoveryImpactKind.DELAY,
            escalation_level=1,
        )
    return RecoveryAssessmentDecision(
        material=False,
        resolve=True,
        impact_kind=RecoveryImpactKind.DELAY,
        escalation_level=0,
    )


async def reconcile_recovery_incident(
    *,
    organization_id: UUID,
    service_queue_id: UUID,
    repository: RecoveryWorkflowRepository,
    capacity: RecoveryCapacitySource,
    current_proposal_id: UUID | None = None,
) -> tuple[RecoveryCapacityAssessment, RecoveryIncident | None]:
    """Re-assess one scope and converge its durable incident onto F4 truth.

    A healthy scope without an existing incident remains a no-op. Existing incidents
    are resolved only from a fresh authoritative assessment; action success alone is
    never treated as proof of recovery.
    """

    assessment = await capacity.assess_recovery_capacity(
        organization_id=organization_id,
        service_queue_id=service_queue_id,
    )
    decision = classify_recovery_assessment(assessment)
    existing = await repository.get_open_incident(
        organization_id=organization_id,
        service_queue_id=service_queue_id,
    )
    if not decision.material and existing is None:
        return assessment, None

    incident = await repository.upsert_assessment(
        organization_id=organization_id,
        service_queue_id=service_queue_id,
        resource_id=assessment.resource_id,
        location_id=assessment.location_id,
        source_revision=assessment.checkpoint.recovery_source_revision,
        source_fingerprint=assessment.source_fingerprint,
        impact_kind=decision.impact_kind,
        escalation_level=decision.escalation_level,
        current_proposal_id=current_proposal_id,
        resolve=decision.resolve,
    )
    return assessment, incident
