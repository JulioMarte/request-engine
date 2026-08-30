from uuid import UUID

from request_engine.modules.booking.contracts.recovery import RecoveryBookingPort
from request_engine.modules.live_capacity.contracts.recovery import RecoveryCapacitySource
from request_engine.modules.operational_recovery.adapters.db.scheduled_assessment_fence import (
    RecoverySourceRevisionReader,
)
from request_engine.modules.operational_recovery.adapters.db.scheduled_assessment_models import (
    ScheduledAssessmentCommit,
)
from request_engine.modules.operational_recovery.adapters.db.scheduled_assessment_store import (
    PostgresScheduledAssessmentStore,
)
from request_engine.modules.operational_recovery.application.proposal_builder import build_proposal
from request_engine.modules.operational_recovery.application.recovery_impact_automation import (
    RecoveryImpactAutomation,
)
from request_engine.platform.scheduling.postgres import ScheduledActionLease
from request_engine.platform.worker.runtime import PermanentWorkError

REASSESS_ACTION_TYPE = "reassess_recovery_scope"
REASSESS_ACTION_VERSION = 1


class RecoveryAssessmentScheduledHandler:
    def __init__(
        self,
        capacity: RecoveryCapacitySource,
        booking: RecoveryBookingPort,
        store: PostgresScheduledAssessmentStore,
        revisions: RecoverySourceRevisionReader,
        impact_automation: RecoveryImpactAutomation,
    ) -> None:
        self._capacity = capacity
        self._booking = booking
        self._store = store
        self._revisions = revisions
        self._impact_automation = impact_automation

    async def handle(self, lease: ScheduledActionLease) -> ScheduledAssessmentCommit:
        if (
            lease.owner_module != "operational_recovery"
            or lease.action_type != REASSESS_ACTION_TYPE
            or lease.action_version != REASSESS_ACTION_VERSION
            or lease.subject_kind != "ServiceQueue"
            or lease.subject_id is None
        ):
            raise PermanentWorkError("unsupported_recovery_scheduled_action")

        raw_queue_id = lease.payload.get("service_queue_id")
        raw_revision = lease.payload.get("source_revision")
        if not isinstance(raw_queue_id, str) or not isinstance(raw_revision, int):
            raise PermanentWorkError("recovery_reassessment_payload_invalid")
        try:
            queue_id = UUID(raw_queue_id)
        except ValueError as exc:
            raise PermanentWorkError("recovery_reassessment_payload_invalid") from exc
        if queue_id != lease.subject_id or raw_revision <= 0:
            raise PermanentWorkError("recovery_reassessment_payload_mismatch")

        current_revision = await self._revisions.read(
            organization_id=lease.organization_id,
            service_queue_id=queue_id,
        )
        if current_revision != raw_revision:
            return ScheduledAssessmentCommit(applied=False, stale=True, incident=None)

        assessment = await self._capacity.assess_recovery_capacity(
            organization_id=lease.organization_id,
            service_queue_id=queue_id,
        )
        proposal = None
        if assessment.shortfall_seconds > 0:
            proposal = await build_proposal(
                organization_id=lease.organization_id,
                search_days=7,
                assessment=assessment,
                booking=self._booking,
            )
        commit = await self._store.commit(
            organization_id=lease.organization_id,
            service_queue_id=queue_id,
            target_source_revision=raw_revision,
            action_id=lease.id,
            claim_token=lease.claim_token,
            assessment=assessment,
            proposal=proposal,
        )
        if (
            commit.applied
            and commit.incident is not None
            and commit.escalation is not None
            and commit.escalation.customer_impact_required
            and commit.escalation.impact_recipient_party_ids
        ):
            await self._impact_automation.communicate_impact(
                organization_id=lease.organization_id,
                incident_id=commit.incident.id,
                source_revision=raw_revision,
                recipients=commit.escalation.impact_recipient_party_ids,
            )
        return commit
