from request_engine.modules.booking.contracts.recovery import RecoveryBookingPort
from request_engine.modules.live_capacity.contracts.recovery import RecoveryCapacitySource
from request_engine.modules.operational_recovery.application.execution_policy import (
    affected_reservation,
    require_target,
)
from request_engine.modules.operational_recovery.application.ports import RecoveryRepository
from request_engine.modules.operational_recovery.application.proposal_ops import get_proposal
from request_engine.modules.operational_recovery.application.workflow_action_execution import (
    authorize_or_resume_action,
)
from request_engine.modules.operational_recovery.application.workflow_assessment import (
    reconcile_recovery_incident,
)
from request_engine.modules.operational_recovery.application.workflow_commands import (
    RescheduleRecoveryActionCommand,
)
from request_engine.modules.operational_recovery.application.workflow_ports import (
    RecoveryWorkflowRepository,
)
from request_engine.modules.operational_recovery.application.workflow_reschedule_owner import (
    execute_booking_reschedule_step,
    reject_reschedule_action,
)
from request_engine.modules.operational_recovery.application.workflow_reschedule_support import (
    reschedule_fingerprint,
    reschedule_payload,
    validate_fresh_reschedule_authorization,
)
from request_engine.modules.operational_recovery.contracts.workflow import (
    RecoveryAction,
    RecoveryActionKind,
    RecoveryActionStatus,
    RecoveryIncidentNotFound,
    RecoveryIncidentStale,
)


async def execute_reschedule_action(
    command: RescheduleRecoveryActionCommand,
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
    require_target(affected)
    payload = reschedule_payload(command)
    action, terminal, newly_authorized = await authorize_or_resume_action(
        repository=workflow_repository,
        incident=incident,
        organization_id=command.organization_id,
        principal_id=command.principal_id,
        action_kind=RecoveryActionKind.RESCHEDULE,
        idempotency_key=command.idempotency_key,
        command_fingerprint=reschedule_fingerprint(command, payload),
        expected_source_revision=command.expected_source_revision,
        payload=payload,
    )
    if terminal:
        return action
    if newly_authorized:
        try:
            validate_fresh_reschedule_authorization(command, incident=incident, proposal=proposal)
        except RecoveryIncidentStale:
            await reject_reschedule_action(
                workflow_repository, command, action, "STALE_RECOVERY_INCIDENT"
            )
            raise
    reservation = await execute_booking_reschedule_step(
        command=command,
        action=action,
        proposal=proposal,
        affected=affected,
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
            "booking_reschedule": {
                "reservation_id": str(reservation.id),
                "revision": reservation.revision,
            },
            "reassessment": {
                "source_revision": assessment.checkpoint.recovery_source_revision,
                "incident_status": None if refreshed is None else refreshed.status.value,
            },
        },
    )
