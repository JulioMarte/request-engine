from request_engine.modules.booking.contracts.recovery_schedule import RecoveryAssignmentSchedulePort
from request_engine.modules.catalog.contracts.recovery_schedule import RecoveryLocationSchedulePort
from request_engine.modules.live_capacity.contracts.recovery import RecoveryCapacitySource
from request_engine.modules.operational_recovery.application.workflow_action_execution import (
    authorize_or_resume_action,
)
from request_engine.modules.operational_recovery.application.workflow_assessment import (
    reconcile_recovery_incident,
)
from request_engine.modules.operational_recovery.application.workflow_commands import (
    ExtendRecoveryDayCommand,
)
from request_engine.modules.operational_recovery.application.workflow_ports import (
    RecoveryWorkflowRepository,
)
from request_engine.modules.operational_recovery.application.workflow_schedule_owners import (
    apply_extend_day_owner_steps,
)
from request_engine.modules.operational_recovery.application.workflow_schedule_support import (
    extend_day_fingerprint,
    extend_day_payload,
    validate_extend_day,
)
from request_engine.modules.operational_recovery.contracts.workflow import (
    RecoveryAction,
    RecoveryActionKind,
    RecoveryActionStatus,
    RecoveryIncidentNotFound,
)


async def execute_extend_day_action(
    command: ExtendRecoveryDayCommand,
    *,
    repository: RecoveryWorkflowRepository,
    location_schedule: RecoveryLocationSchedulePort,
    assignment_schedule: RecoveryAssignmentSchedulePort,
    capacity: RecoveryCapacitySource,
) -> RecoveryAction:
    validate_extend_day(command)
    incident = await repository.get_incident(
        organization_id=command.organization_id,
        incident_id=command.incident_id,
    )
    if incident is None:
        raise RecoveryIncidentNotFound(command.incident_id)

    payload = extend_day_payload(command)
    action, terminal = await authorize_or_resume_action(
        repository=repository,
        incident=incident,
        organization_id=command.organization_id,
        principal_id=command.principal_id,
        action_kind=RecoveryActionKind.EXTEND_DAY,
        idempotency_key=command.idempotency_key,
        command_fingerprint=extend_day_fingerprint(command, payload),
        expected_source_revision=command.expected_source_revision,
        payload=payload,
    )
    if terminal:
        return action

    action = await apply_extend_day_owner_steps(
        command,
        incident=incident,
        action=action,
        repository=repository,
        location_schedule=location_schedule,
        assignment_schedule=assignment_schedule,
    )
    assessment, refreshed = await reconcile_recovery_incident(
        organization_id=command.organization_id,
        service_queue_id=incident.service_queue_id,
        repository=repository,
        capacity=capacity,
        current_proposal_id=incident.current_proposal_id,
    )
    if assessment.checkpoint.recovery_source_revision <= command.expected_source_revision:
        raise RuntimeError("extend-day owner mutations did not advance recovery source revision")
    return await repository.transition_action(
        organization_id=command.organization_id,
        action_id=action.id,
        expected_status=RecoveryActionStatus.RUNNING,
        status=RecoveryActionStatus.SUCCEEDED,
        owner_steps={
            **action.owner_steps,
            "reassessment": {
                "source_revision": assessment.checkpoint.recovery_source_revision,
                "source_fingerprint": assessment.source_fingerprint,
                "projection_state": assessment.projection_state.value,
                "scheduled_shortfall_seconds": assessment.scheduled_shortfall_seconds,
                "live_shortfall_seconds": assessment.live_shortfall_seconds,
                "incident_status": None if refreshed is None else refreshed.status.value,
            },
        },
    )
