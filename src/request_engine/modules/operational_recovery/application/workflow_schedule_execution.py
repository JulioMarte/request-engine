from request_engine.modules.booking.contracts.recovery_schedule import (
    RecoveryAssignmentRevisionConflict,
    RecoveryAssignmentSchedulePort,
)
from request_engine.modules.live_capacity.contracts.recovery import RecoveryCapacitySource
from request_engine.modules.operational_recovery.application.workflow_assessment import (
    reconcile_recovery_incident,
)
from request_engine.modules.operational_recovery.application.workflow_commands import (
    ExtendRecoveryDayCommand,
)
from request_engine.modules.operational_recovery.application.workflow_location_port import (
    RecoveryLocationExtensionPort,
    RecoveryLocationRevisionConflict,
)
from request_engine.modules.operational_recovery.application.workflow_ports import (
    RecoveryWorkflowRepository,
)
from request_engine.modules.operational_recovery.application.workflow_schedule_owners import (
    apply_extend_day_owner_steps,
)
from request_engine.modules.operational_recovery.contracts.workflow import (
    RecoveryAction,
    RecoveryActionStatus,
    RecoveryIncident,
    RecoveryOwnerRevisionConflict,
)


async def complete_extend_day_execution(
    command: ExtendRecoveryDayCommand,
    *,
    incident: RecoveryIncident,
    action: RecoveryAction,
    repository: RecoveryWorkflowRepository,
    location_schedule: RecoveryLocationExtensionPort,
    assignment_schedule: RecoveryAssignmentSchedulePort,
    capacity: RecoveryCapacitySource,
) -> RecoveryAction:
    try:
        action = await apply_extend_day_owner_steps(
            command,
            incident=incident,
            action=action,
            repository=repository,
            location_schedule=location_schedule,
            assignment_schedule=assignment_schedule,
        )
    except RecoveryLocationRevisionConflict as exc:
        raise RecoveryOwnerRevisionConflict(
            owner="catalog_location",
            scope_id=exc.location_id,
            expected=exc.expected,
            actual=exc.actual,
        ) from exc
    except RecoveryAssignmentRevisionConflict as exc:
        raise RecoveryOwnerRevisionConflict(
            owner="booking_schedule",
            scope_id=exc.assignment_id,
            expected=exc.expected,
            actual=exc.actual,
        ) from exc

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
