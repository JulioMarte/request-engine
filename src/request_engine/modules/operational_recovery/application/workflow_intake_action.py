from request_engine.modules.operational_recovery.application.workflow_commands import (
    SetRecoveryIntakeCommand,
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
from request_engine.modules.queue.contracts.intake import (
    QueueIntakeControlPort,
    SetQueueIntakeControlRequest,
)
from request_engine.platform.idempotency.postgres import command_fingerprint


async def execute_intake_action(
    command: SetRecoveryIntakeCommand,
    *,
    repository: RecoveryWorkflowRepository,
    queue_intake: QueueIntakeControlPort,
) -> RecoveryAction:
    incident = await repository.get_incident(
        organization_id=command.organization_id,
        incident_id=command.incident_id,
    )
    if incident is None:
        raise RecoveryIncidentNotFound(command.incident_id)
    if incident.status is RecoveryIncidentStatus.RESOLVED:
        raise RecoveryIncidentStale(
            command.incident_id,
            command.expected_source_revision,
            incident.source_revision,
        )
    if incident.source_revision != command.expected_source_revision:
        raise RecoveryIncidentStale(
            command.incident_id,
            command.expected_source_revision,
            incident.source_revision,
        )

    action_kind = (
        RecoveryActionKind.REOPEN_INTAKE if command.accepting else RecoveryActionKind.STOP_INTAKE
    )
    payload: dict[str, object] = {
        "accepting": command.accepting,
        "reason": command.reason,
        "effective_until": command.effective_until,
    }
    fingerprint = command_fingerprint(
        f"operational_recovery.{action_kind.value}.v1",
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
        action_kind=action_kind,
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

    await repository.transition_action(
        organization_id=command.organization_id,
        action_id=action.id,
        status=RecoveryActionStatus.RUNNING,
    )
    current = await queue_intake.get_intake_control(
        command.organization_id,
        incident.service_queue_id,
    )
    result = await queue_intake.set_intake_control(
        SetQueueIntakeControlRequest(
            organization_id=command.organization_id,
            principal_id=command.principal_id,
            service_queue_id=incident.service_queue_id,
            accepting=command.accepting,
            expected_revision=current.revision,
            idempotency_key=f"recovery-action:{action.id}:queue-intake:v1",
            reason=command.reason,
            effective_until=command.effective_until,
        )
    )
    return await repository.transition_action(
        organization_id=command.organization_id,
        action_id=action.id,
        status=RecoveryActionStatus.SUCCEEDED,
        owner_steps={
            "queue_intake": {
                "service_queue_id": str(result.service_queue_id),
                "revision": result.revision,
                "accepting": result.accepting,
            }
        },
    )
