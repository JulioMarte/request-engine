from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text

from request_engine.modules.live_capacity.contracts.recovery import RecoveryCapacityAssessment
from request_engine.modules.operational_recovery.adapters.db.automatic_proposal_store import (
    insert_automatic_proposal,
)
from request_engine.modules.operational_recovery.adapters.db.scheduled_assessment_idempotency import (
    incident_matches_assessment,
)
from request_engine.modules.operational_recovery.adapters.db.workflow_incident_queries import (
    get_open_incident_row,
)
from request_engine.modules.operational_recovery.adapters.db.workflow_incident_write import (
    insert_incident,
    update_incident,
)
from request_engine.modules.operational_recovery.application.workflow_assessment import (
    classify_recovery_assessment,
)
from request_engine.modules.operational_recovery.contracts.models import RescheduleProposal
from request_engine.modules.operational_recovery.contracts.workflow import RecoveryIncident
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.scheduling.store import lock_action_claim
from request_engine.platform.worker.runtime import LeaseLostWorkError


@dataclass(frozen=True, slots=True)
class ScheduledAssessmentCommit:
    applied: bool
    stale: bool
    incident: RecoveryIncident | None
    proposal_id: UUID | None = None


class PostgresScheduledAssessmentStore:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def commit(
        self,
        *,
        organization_id: UUID,
        service_queue_id: UUID,
        target_source_revision: int,
        action_id: UUID,
        claim_token: UUID,
        assessment: RecoveryCapacityAssessment,
        proposal: RescheduleProposal | None = None,
    ) -> ScheduledAssessmentCommit:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            if not await lock_action_claim(session, action_id=action_id, claim_token=claim_token):
                raise LeaseLostWorkError("recovery_reassessment_authoritative_fence_lost")
            current = (
                await session.execute(
                    text(
                        "SELECT revision FROM request_engine.recovery_source_revisions "
                        "WHERE organization_id=:organization_id "
                        "AND service_queue_id=:service_queue_id FOR UPDATE"
                    ),
                    {"organization_id": organization_id, "service_queue_id": service_queue_id},
                )
            ).scalar_one()
            if (
                current != target_source_revision
                or assessment.checkpoint.recovery_source_revision != target_source_revision
            ):
                return ScheduledAssessmentCommit(applied=False, stale=True, incident=None)

            decision = classify_recovery_assessment(assessment)
            existing = await get_open_incident_row(
                session,
                organization_id=organization_id,
                service_queue_id=service_queue_id,
                lock=True,
            )
            if not decision.material and existing is None:
                return ScheduledAssessmentCommit(applied=False, stale=False, incident=None)

            proposal_id: UUID | None = None
            if decision.material and assessment.shortfall_seconds > 0:
                if proposal is None:
                    raise ValueError("material shortfall assessment requires a proposal")
                if (
                    proposal.service_queue_id != service_queue_id
                    or proposal.source_fingerprint != assessment.source_fingerprint
                    or proposal.source_checkpoint.recovery_source_revision != target_source_revision
                ):
                    raise ValueError("automatic recovery proposal does not match assessment")
                proposal_id = await insert_automatic_proposal(
                    session,
                    organization_id=organization_id,
                    source_revision=target_source_revision,
                    proposal=proposal,
                )

            if existing is not None and incident_matches_assessment(
                existing,
                source_revision=target_source_revision,
                source_fingerprint=assessment.source_fingerprint,
                proposal_id=proposal_id,
                decision=decision,
            ):
                return ScheduledAssessmentCommit(
                    applied=False,
                    stale=False,
                    incident=existing,
                    proposal_id=proposal_id,
                )

            if existing is None:
                incident = await insert_incident(
                    session,
                    organization_id=organization_id,
                    service_queue_id=service_queue_id,
                    resource_id=assessment.resource_id,
                    location_id=assessment.location_id,
                    source_revision=target_source_revision,
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
                    source_revision=target_source_revision,
                    source_fingerprint=assessment.source_fingerprint,
                    impact_kind=decision.impact_kind,
                    escalation_level=decision.escalation_level,
                    current_proposal_id=proposal_id,
                    resolve=decision.resolve,
                )
            return ScheduledAssessmentCommit(
                applied=True,
                stale=False,
                incident=incident,
                proposal_id=proposal_id,
            )
