from request_engine.modules.booking.contracts.recovery import RecoveryBookingPort
from request_engine.modules.live_capacity.contracts.recovery import RecoveryCapacitySource
from request_engine.modules.operational_recovery.application import (
    workflow_replace_resource_owner as replace_owner,
)
from request_engine.modules.operational_recovery.application import (
    workflow_replace_resource_support as replace_support,
)
from request_engine.modules.operational_recovery.application.execution_policy import (
    affected_reservation,
    require_recovery_target,
)
from request_engine.modules.operational_recovery.application.ports import RecoveryRepository
from request_engine.modules.operational_recovery.application.proposal_ops import get_proposal
from request_engine.modules.operational_recovery.application.workflow_assessment import (
    reconcile_recovery_incident,
)
from request_engine.modules.operational_recovery.application.workflow_commands import (
    ReplaceResourceRecoveryActionCommand,
)
from request_engine.modules.operational_recovery.application.workflow_ports import (
    RecoveryWorkflowRepository,
)
from request_engine.modules.operational_recovery.application.workflow_replace_external import (
    execute_external_replacement,
)
from request_engine.modules.operational_recovery.contracts.workflow import (
    RecoveryAction,
    RecoveryActionStatus,
    RecoveryIncidentNotFound,
)


async def execute_replace_resource_action(
    command: ReplaceResourceRecoveryActionCommand,
    *,
    workflow_repository: RecoveryWorkflowRepository,
    proposal_repository: RecoveryRepository,
    booking: RecoveryBookingPort,
    capacity: RecoveryCapacitySource,
) -> RecoveryAction:
    incident = await workflow_repository.get_incident(
        organization_id=command.organization_id, incident_id=command.incident_id
    )
    if incident is None:
        raise RecoveryIncidentNotFound(command.incident_id)
    proposal = await get_proposal(
        repository=proposal_repository,
        organization_id=command.organization_id,
        proposal_id=command.proposal_id,
    )
    affected = affected_reservation(proposal, command.reservation_id)
    action, terminal = await replace_support.authorize_replace_resource(
        command,
        workflow_repository=workflow_repository,
        incident=incident,
        proposal=proposal,
    )
    if terminal:
        return action
    if command.external_target is not None:
        return await execute_external_replacement(
            command,
            action=action,
            incident=incident,
            affected=affected,
            workflow_repository=workflow_repository,
            booking=booking,
            capacity=capacity,
        )
    target = require_recovery_target(command.reservation_id, affected.replacement_target)
    reservation = await replace_owner.execute_booking_replace_resource_step(
        command=command,
        action=action,
        proposal=proposal,
        affected=affected,
        target=target,
        repository=workflow_repository,
        booking=booking,
    )
    assessment, refreshed = await reconcile_recovery_incident(
        organization_id=command.organization_id,
        service_queue_id=incident.service_queue_id,
        repository=workflow_repository,
        capacity=capacity,
        current_proposal_id=incident.current_proposal_id,
    )
    return await workflow_repository.transition_action(
        organization_id=command.organization_id,
        action_id=action.id,
        expected_status=action.status,
        status=RecoveryActionStatus.SUCCEEDED,
        owner_steps={
            "booking_replace_resource": {
                "reservation_id": str(reservation.id),
                "revision": reservation.revision,
            },
            "reassessment": {
                "source_revision": assessment.checkpoint.recovery_source_revision,
                "incident_status": None if refreshed is None else refreshed.status.value,
            },
        },
    )
