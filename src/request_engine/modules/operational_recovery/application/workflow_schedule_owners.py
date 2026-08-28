from request_engine.modules.booking.contracts.recovery_schedule import (
    RecoveryAssignmentExtensionRequest,
    RecoveryAssignmentSchedulePort,
)
from request_engine.modules.operational_recovery.application.workflow_commands import (
    ExtendRecoveryDayCommand,
)
from request_engine.modules.operational_recovery.application.workflow_location_port import (
    RecoveryLocationExtensionPort,
    RecoveryLocationExtensionRequest,
)
from request_engine.modules.operational_recovery.application.workflow_ports import (
    RecoveryWorkflowRepository,
)
from request_engine.modules.operational_recovery.contracts.workflow import (
    RecoveryAction,
    RecoveryActionStatus,
    RecoveryIncident,
)


async def apply_extend_day_owner_steps(
    command: ExtendRecoveryDayCommand,
    *,
    incident: RecoveryIncident,
    action: RecoveryAction,
    repository: RecoveryWorkflowRepository,
    location_schedule: RecoveryLocationExtensionPort,
    assignment_schedule: RecoveryAssignmentSchedulePort,
) -> RecoveryAction:
    location = await location_schedule.extend_location_hours(
        RecoveryLocationExtensionRequest(
            organization_id=command.organization_id,
            principal_id=command.principal_id,
            authority_party_id=command.authority_party_id,
            location_id=incident.location_id,
            start_at=command.start_at,
            end_at=command.end_at,
            expected_operational_revision=command.expected_location_operational_revision,
            idempotency_key=f"recovery-action:{action.id}:location-hours:v1",
            reason=command.reason,
        )
    )
    action = await repository.transition_action(
        organization_id=command.organization_id,
        action_id=action.id,
        expected_status=RecoveryActionStatus.RUNNING,
        status=RecoveryActionStatus.RUNNING,
        owner_steps={
            **action.owner_steps,
            "catalog_location": {
                "exception_id": str(location.exception_id),
                "location_id": str(location.location_id),
                "operational_revision": location.operational_revision,
            },
        },
    )
    assignment = await assignment_schedule.extend_assignment_hours(
        RecoveryAssignmentExtensionRequest(
            organization_id=command.organization_id,
            principal_id=command.principal_id,
            authority_party_id=command.authority_party_id,
            assignment_id=command.assignment_id,
            start_at=command.start_at,
            end_at=command.end_at,
            expected_resource_availability_revision=(
                command.expected_resource_availability_revision
            ),
            idempotency_key=f"recovery-action:{action.id}:assignment-hours:v1",
            reason=command.reason,
        )
    )
    return await repository.transition_action(
        organization_id=command.organization_id,
        action_id=action.id,
        expected_status=RecoveryActionStatus.RUNNING,
        status=RecoveryActionStatus.RUNNING,
        owner_steps={
            **action.owner_steps,
            "booking_schedule": {
                "exception_id": str(assignment.exception_id),
                "assignment_id": str(assignment.assignment_id),
                "resource_availability_revision": assignment.resource_availability_revision,
            },
        },
    )
