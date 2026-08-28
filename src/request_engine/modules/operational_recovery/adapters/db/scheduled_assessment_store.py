from uuid import UUID

from request_engine.modules.live_capacity.contracts.recovery import RecoveryCapacityAssessment
from request_engine.modules.operational_recovery.application.workflow_assessment import (
    classify_recovery_assessment,
)
from request_engine.modules.operational_recovery.contracts.models import RescheduleProposal
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.scheduling.store import lock_action_claim
from request_engine.platform.worker.runtime import LeaseLostWorkError

from .automatic_proposal_store import find_automatic_proposal_id
from .scheduled_assessment_fence import lock_recovery_source_revision
from .scheduled_assessment_idempotency import incident_matches_assessment
from .scheduled_assessment_models import ScheduledAssessmentCommit
from .scheduled_assessment_proposal import automatic_proposal_for_assessment
from .workflow_incident_queries import get_open_incident_row
from .workflow_incident_write import insert_incident, update_incident


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
            current = await lock_recovery_source_revision(
                session,
                organization_id=organization_id,
                service_queue_id=service_queue_id,
            )
            if (
                current != target_source_revision
                or assessment.checkpoint.recovery_source_revision != target_source_revision
            ):
                return ScheduledAssessmentCommit(applied=False, stale=True, incident=None)

            existing = await get_open_incident_row(
                session,
                organization_id=organization_id,
                service_queue_id=service_queue_id,
                lock=True,
            )
            persisted_proposal_id = await find_automatic_proposal_id(
                session,
                organization_id=organization_id,
                service_queue_id=service_queue_id,
                source_revision=target_source_revision,
            )
            if (
                existing is not None
                and existing.source_revision == target_source_revision
                and persisted_proposal_id is not None
                and existing.current_proposal_id == persisted_proposal_id
            ):
                return ScheduledAssessmentCommit(
                    applied=False,
                    stale=False,
                    incident=existing,
                    proposal_id=persisted_proposal_id,
                )

            decision = classify_recovery_assessment(assessment)
            if not decision.material and existing is None:
                return ScheduledAssessmentCommit(applied=False, stale=False, incident=None)

            proposal_id = await automatic_proposal_for_assessment(
                session,
                organization_id=organization_id,
                service_queue_id=service_queue_id,
                source_revision=target_source_revision,
                assessment=assessment,
                decision=decision,
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
