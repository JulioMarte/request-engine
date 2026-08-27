from request_engine.modules.booking.contracts.recovery_schedule import (
    RecoveryAssignmentExtensionRequest,
    RecoveryAssignmentSchedulePort,
)
from request_engine.modules.live_capacity.contracts.recovery import RecoveryCapacitySource
from request_engine.modules.operational_recovery.application.workflow_assessment import (
    reconcile_recovery_incident,
)
from request_engine.modules.operational_recovery.application.workflow_commands import ExtendRecoveryDayCommand
from request_engine.modules.operational_recovery.application.workflow_ports import RecoveryWorkflowRepository
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
    RecoveryIncidentStale,
    RecoveryIncidentStatus,
)


async def execute_extend_day_action(
    command: ExtendRecoveryDayCommand,
    *,
    repository: RecoveryWorkflowRepository,
    schedule: RecoveryAssignmentSchedulePort,
    capacity: RecoveryCapacitySource,
) -> RecoveryAction:
    validate_extend_day(command)
    incident = await repository.get_incident(
        organization_id=command.organization_id,
        incident_id=command.incident_id,
    )
    if incident is None:
        raise RecoveryIncidentNotFound(command.incident_id)
    if (
        incident.status is RecoveryIncidentStatus.RESOLVED
        or incident.source_revision != command.expected_source_revision
    ):
        raise RecoveryIncidentStale(
            command.incident_id,
            command.expected_source_revision,
            incident.source_revision,
        )

    payload = extend_day_payload(command)
    action, created = await repository.prepare_action(
        organization_id=command.organization_id,
        incident_id=command.incident_id,
        principal_id=command.principal_id,
        action_kind=RecoveryActionKind.EXTEND_DAY,
        idempotency_key=command.idempotency_key,
        command_fingerprint=extend_day_fingerprint(command, payload),
        expected_source_revision=command.expected_source_revision,
        payload=payload,
    )
    if not created and action.status in {
        RecoveryActionStatus.SUCCEEDED,
        RecoveryActionStatus.REJECTED,
    }:
        return action
    if action.status is RecoveryActionStatus.PREPARED:
        action = await repository.transition_action(
            organization_id=command.organization_id,
            action_id=action.id,
            status=RecoveryActionStatus.RUNNING,
        )

    result = await schedule.extend_assignment_hours(
        RecoveryAssignmentExtensionRequest(
            organization_id=command.organization_id,
            principal_id=command.principal_id,
            authority_party_id=command.authority_party_id,
            assignment_id=command.assignment_id,
            start_at=command.start_at,
            end_at=command.end_at,
            expected_resource_availability_revision=command.expected_resource_availability_revision,
            idempotency_key=f"recovery-action:{action.id}:extend-day:v1",
            reason=command.reason,
        )
    )
    assessment, refreshed = await reconcile_recovery_incident(
        organization_id=command.organization_id,
        service_queue_id=incident.service_queue_id,
        repository=repository,
        capacity=capacity,
        current_proposal_id=incident.current_proposal_id,
    )
    if assessment.checkpoint.recovery_source_revision <= command.expected_source_revision:
        raise RuntimeError("extend-day owner mutation did not advance recovery source revision")
    return await repository.transition_action(
        organization_id=command.organization_id,
        action_id=action.id,
        status=RecoveryActionStatus.SUCCEEDED,
        owner_steps={
            "booking_schedule": {
                "exception_id": str(result.exception_id),
                "assignment_id": str(result.assignment_id),
                "resource_availability_revision": result.resource_availability_revision,
            },
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
