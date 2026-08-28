from uuid import UUID

from request_engine.modules.communications.contracts.recovery import (
    RecoveryCommunicationPort,
    RecoveryCommunicationPurpose,
    RecoveryCommunicationRequest,
)
from request_engine.modules.operational_recovery.application.workflow_action_execution import (
    authorize_or_resume_action,
)
from request_engine.modules.operational_recovery.application.workflow_commands import (
    CommunicateImpactRecoveryActionCommand,
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


def impact_dedupe_key(*, incident_id: UUID, recipient_party_id: UUID, source_revision: int) -> str:
    """Section 13 identity: incident + recipient + purpose + source revision."""

    return f"operational-recovery:{incident_id}:impact:{recipient_party_id}:{source_revision}"


async def execute_communicate_impact_action(
    command: CommunicateImpactRecoveryActionCommand,
    *,
    repository: RecoveryWorkflowRepository,
    communications: RecoveryCommunicationPort,
) -> RecoveryAction:
    if command.expected_source_revision <= 0:
        raise ValueError("expected_source_revision must be positive")
    incident = await repository.get_incident(
        organization_id=command.organization_id,
        incident_id=command.incident_id,
    )
    if incident is None:
        raise RecoveryIncidentNotFound(command.incident_id)

    payload: dict[str, object] = {
        "recipient_party_id": str(command.recipient_party_id),
        "message": command.message,
        "not_before": command.not_before,
    }
    fingerprint = command_fingerprint(
        f"operational_recovery.{RecoveryActionKind.COMMUNICATE_IMPACT.value}.v1",
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
        action_kind=RecoveryActionKind.COMMUNICATE_IMPACT,
        idempotency_key=command.idempotency_key,
        command_fingerprint=fingerprint,
        expected_source_revision=command.expected_source_revision,
        payload=payload,
    )
    if terminal:
        return action

    task = await communications.create_recovery_notification(
        RecoveryCommunicationRequest(
            organization_id=command.organization_id,
            principal_id=command.principal_id,
            recipient_party_id=command.recipient_party_id,
            purpose=RecoveryCommunicationPurpose.IMPACT,
            execution_id=command.incident_id,
            idempotency_key=(
                f"recovery-impact:{command.incident_id}:"
                f"{command.recipient_party_id}:{command.expected_source_revision}:v1"
            ),
            dedupe_key=impact_dedupe_key(
                incident_id=command.incident_id,
                recipient_party_id=command.recipient_party_id,
                source_revision=command.expected_source_revision,
            ),
            render_context={"message": command.message} if command.message else {},
            not_before=command.not_before,
        )
    )
    return await repository.transition_action(
        organization_id=command.organization_id,
        action_id=action.id,
        expected_status=RecoveryActionStatus.RUNNING,
        status=RecoveryActionStatus.SUCCEEDED,
        owner_steps={
            "communications": {
                "communication_task_id": str(task.id),
                "dedupe_key": task.dedupe_key,
                "status": task.status.value,
            }
        },
    )
