from request_engine.modules.booking.contracts.recovery_schedule import (
    RecoveryAssignmentSchedulePort,
)
from request_engine.modules.live_capacity.contracts.recovery import RecoveryCapacitySource
from request_engine.modules.operational_recovery.application.workflow_action_execution import (
    authorize_or_resume_action,
)
from request_engine.modules.operational_recovery.application.workflow_commands import (
    ExtendRecoveryDayCommand,
)
from request_engine.modules.operational_recovery.application.workflow_location_port import (
    RecoveryLocationExtensionPort,
)
from request_engine.modules.operational_recovery.application.workflow_ports import (
    RecoveryWorkflowRepository,
)
from request_engine.modules.operational_recovery.application.workflow_schedule_execution import (
    complete_extend_day_execution,
)
from request_engine.modules.operational_recovery.application.workflow_schedule_support import (
    extend_day_fingerprint,
    extend_day_payload,
    validate_extend_day,
)
from request_engine.modules.operational_recovery.contracts.workflow import (
    RecoveryAction,
    RecoveryActionKind,
    RecoveryIncidentNotFound,
)


async def execute_extend_day_action(
    command: ExtendRecoveryDayCommand,
    *,
    repository: RecoveryWorkflowRepository,
    location_schedule: RecoveryLocationExtensionPort,
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
    fingerprint = extend_day_fingerprint(command, payload)
    prepared, _ = await repository.prepare_action(
        organization_id=command.organization_id,
        incident_id=incident.id,
        principal_id=command.principal_id,
        action_kind=RecoveryActionKind.EXTEND_DAY,
        idempotency_key=command.idempotency_key,
        command_fingerprint=fingerprint,
        expected_source_revision=command.expected_source_revision,
        payload=payload,
    )

    async with repository.serialize_action_execution(action_id=prepared.id):
        incident = await repository.get_incident(
            organization_id=command.organization_id,
            incident_id=command.incident_id,
        )
        if incident is None:
            raise RecoveryIncidentNotFound(command.incident_id)
        action, terminal, _ = await authorize_or_resume_action(
            repository=repository,
            incident=incident,
            organization_id=command.organization_id,
            principal_id=command.principal_id,
            action_kind=RecoveryActionKind.EXTEND_DAY,
            idempotency_key=command.idempotency_key,
            command_fingerprint=fingerprint,
            expected_source_revision=command.expected_source_revision,
            payload=payload,
        )
        if terminal:
            return action
        return await complete_extend_day_execution(
            command,
            incident=incident,
            action=action,
            repository=repository,
            location_schedule=location_schedule,
            assignment_schedule=assignment_schedule,
            capacity=capacity,
        )
