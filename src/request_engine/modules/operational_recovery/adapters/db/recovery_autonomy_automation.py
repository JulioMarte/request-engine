from uuid import UUID

from request_engine.modules.booking.contracts.recovery import RecoveryBookingPort
from request_engine.modules.communications.contracts.recovery import RecoveryCommunicationPort
from request_engine.modules.live_capacity.contracts.recovery import RecoveryCapacitySource
from request_engine.modules.operational_recovery.adapters.db.recovery_automation_principal import (
    RecoveryAutomationPrincipal,
)
from request_engine.modules.operational_recovery.application.ports import RecoveryRepository
from request_engine.modules.operational_recovery.application.proposal_ops import get_proposal
from request_engine.modules.operational_recovery.application.recovery_autonomy_execution import (
    execute_autonomy_plan,
)
from request_engine.modules.operational_recovery.application.recovery_autonomy_policy import (
    RecoveryAutonomyPolicyReader,
    autonomous_execution_plan,
)
from request_engine.modules.operational_recovery.application.workflow_ports import (
    RecoveryWorkflowRepository,
)
from request_engine.platform.db.session import SessionFactory


class PostgresRecoveryRescheduleAutonomy:
    """Reads the queue's operator-granted envelope, plans the persisted
    proposal's reschedule work, and executes it under the automation principal
    through the application's own reschedule command semantics."""

    def __init__(
        self,
        session_factory: SessionFactory,
        reader: RecoveryAutonomyPolicyReader,
        workflow_repository: RecoveryWorkflowRepository,
        proposal_repository: RecoveryRepository,
        booking: RecoveryBookingPort,
        capacity: RecoveryCapacitySource,
        communications: RecoveryCommunicationPort,
    ) -> None:
        self._reader = reader
        self._workflow = workflow_repository
        self._proposals = proposal_repository
        self._booking = booking
        self._capacity = capacity
        self._communications = communications
        self._principal = RecoveryAutomationPrincipal(session_factory)

    async def reschedule_within_envelope(
        self,
        *,
        organization_id: UUID,
        incident_id: UUID,
        service_queue_id: UUID,
        proposal_id: UUID,
        source_revision: int,
    ) -> None:
        policy = await self._reader.active_policy(
            organization_id=organization_id, service_queue_id=service_queue_id
        )
        if policy is None:
            return
        proposal = await get_proposal(
            repository=self._proposals, organization_id=organization_id, proposal_id=proposal_id
        )
        attempts = await self._reader.autonomous_attempt_keys(
            organization_id=organization_id, incident_id=incident_id
        )
        plan = autonomous_execution_plan(
            policy,
            proposal,
            incident_id=incident_id,
            source_revision=source_revision,
            attempt_keys=attempts,
        )
        if not plan:
            return
        principal_id = await self._principal.ensure(organization_id)
        await execute_autonomy_plan(
            organization_id=organization_id,
            incident_id=incident_id,
            proposal=proposal,
            source_revision=source_revision,
            plan=plan,
            principal_id=principal_id,
            workflow_repository=self._workflow,
            proposal_repository=self._proposals,
            booking=self._booking,
            capacity=self._capacity,
            communications=self._communications,
        )
