from request_engine.modules.booking.contracts.recovery_schedule import (
    RecoveryAssignmentExtensionRequest,
    RecoveryAssignmentSchedulePort,
)
from request_engine.modules.operational_recovery.application.workflow_commands import (
    ExtendRecoveryDayCommand,
)
from request_engine.modules.operational_recovery.application.workflow_ports import (
    RecoveryWorkflowRepository,
)
from request_engine.modules.operational_recovery.contracts.workflow import (
    RecoveryAction,
    RecoveryActionKind,
    RecoveryActionStatus,
    RecoveryIncidentNotFound,
    RecoveryIncidentStale,
    RecoveryIncidentStatus,
)
from request_engine.platform.idempotency.postgres import command_fingerprint


async def execute_extend_day_action(
    command: ExtendRecoveryDayCommand,
    *,
    repository: RecoveryWorkflowRepository,
    schedule: RecoveryAssignmentSchedulePort,
) -> RecoveryAction:
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    if command.expected_source_revision <= 0:
        raise ValueError("expected_source_revision must be positive")
    if command.expected_resource_availability_revision <= 0:
        raise ValueError("expected_resource_availability_revision must be positive")
    if not command.reason.strip():
        raise ValueError("reason is required")
    if command.start_at.tzinfo is None or command.start_at.utcoffset() is None:
        raise ValueError("start_at must be timezone-aware")
    if command.end_at.tzinfo is None or command.end_at.utcoffset() is None:
        raise ValueError("end_at must be timezone-aware")
    if command.end_at <= command.start_at:
        raise ValueError("end_at must be after start_at")

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

    payload: dict[str, object] = {
        "authority_party_id": command.authority_party_id,
        "assignment_id": command.assignment_id,
        "start_at": command.start_at,
        "end_at": command.end_at,
        "expected_resource_availability_revision": (
            command.expected_resource_availability_revision
        ),
        "reason": command.reason,
    }
    fingerprint = command_fingerprint(
        "operational_recovery.extend_day.v1",
        {
            "incident_id": command.incident_id,
            "expected_source_revision": command.expected_source_revision,
            **payload,
        },
    )
    action, created = await repository.prepare_action(
        organization_id=command.organization_id,
        incident_id=command.incident_id,
        principal_id=command.principal_id,
        action_kind=RecoveryActionKind.EXTEND_DAY,
        idempotency_key=command.idempotency_key,
        command_fingerprint=fingerprint,
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
            expected_resource_availability_revision=(
                command.expected_resource_availability_revision
            ),
            idempotency_key=f"recovery-action:{action.id}:extend-day:v1",
            reason=command.reason,
        )
    )
    return await repository.transition_action(
        organization_id=command.organization_id,
        action_id=action.id,
        status=RecoveryActionStatus.SUCCEEDED,
        owner_steps={
            "booking_schedule": {
                "exception_id": str(result.exception_id),
                "assignment_id": str(result.assignment_id),
                "start_at": result.start_at.isoformat(),
                "end_at": result.end_at.isoformat(),
                "resource_availability_revision": result.resource_availability_revision,
            }
        },
    )
