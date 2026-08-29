from request_engine.modules.operational_recovery.application.workflow_action_execution import (
    authorize_or_resume_action,
)
from request_engine.modules.operational_recovery.application.workflow_commands import (
    SetRecoveryIntakeCommand,
)
from request_engine.modules.operational_recovery.application.workflow_intake_port import (
    RecoveryIntakeControlPort,
    RecoveryIntakeControlRequest,
)
from request_engine.modules.operational_recovery.application.workflow_ports import (
    RecoveryWorkflowRepository,
)
from request_engine.modules.operational_recovery.contracts.workflow import (
    RecoveryAction,
    RecoveryActionKind,
    RecoveryActionStatus,
    RecoveryIncidentNotFound,
)
from request_engine.platform.idempotency.postgres import command_fingerprint


async def execute_intake_action(
    command: SetRecoveryIntakeCommand,
    *,
    repository: RecoveryWorkflowRepository,
    queue_intake: RecoveryIntakeControlPort,
) -> RecoveryAction:
    if command.expected_intake_revision <= 0:
        raise ValueError("expected_intake_revision must be positive")
    incident = await repository.get_incident(
        organization_id=command.organization_id,
        incident_id=command.incident_id,
    )
    if incident is None:
        raise RecoveryIncidentNotFound(command.incident_id)

    action_kind = (
        RecoveryActionKind.REOPEN_INTAKE if command.accepting else RecoveryActionKind.STOP_INTAKE
    )
    payload: dict[str, object] = {
        "expected_intake_revision": command.expected_intake_revision,
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
    action, terminal, _ = await authorize_or_resume_action(
        repository=repository,
        incident=incident,
        organization_id=command.organization_id,
        principal_id=command.principal_id,
        action_kind=action_kind,
        idempotency_key=command.idempotency_key,
        command_fingerprint=fingerprint,
        expected_source_revision=command.expected_source_revision,
        payload=payload,
    )
    if terminal:
        return action

    result = await queue_intake.set_recovery_intake_control(
        RecoveryIntakeControlRequest(
            organization_id=command.organization_id,
            principal_id=command.principal_id,
            service_queue_id=incident.service_queue_id,
            expected_revision=command.expected_intake_revision,
            accepting=command.accepting,
            idempotency_key=f"recovery-action:{action.id}:queue-intake:v1",
            reason=command.reason,
            effective_until=command.effective_until,
        )
    )
    return await repository.transition_action(
        organization_id=command.organization_id,
        action_id=action.id,
        expected_status=RecoveryActionStatus.RUNNING,
        status=RecoveryActionStatus.SUCCEEDED,
        owner_steps={
            "queue_intake": {
                "service_queue_id": str(result.service_queue_id),
                "revision": result.revision,
                "accepting": result.accepting,
            }
        },
    )
