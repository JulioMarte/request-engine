from request_engine.modules.communications.contracts.recovery import (
    RecoveryCommunicationPort,
    RecoveryCommunicationPurpose,
    RecoveryCommunicationRequest,
)
from request_engine.modules.operational_recovery.application.commands import ExecuteRecoveryCommand
from request_engine.modules.operational_recovery.application.ports import RecoveryRepository
from request_engine.modules.operational_recovery.contracts.models import (
    AffectedReservation,
    RecoveryExecution,
    RecoveryExecutionStatus,
)


async def ensure_notification(
    *,
    command: ExecuteRecoveryCommand,
    affected: AffectedReservation,
    execution: RecoveryExecution,
    communications: RecoveryCommunicationPort,
    repository: RecoveryRepository,
) -> RecoveryExecution:
    if execution.status is not RecoveryExecutionStatus.SUCCEEDED:
        raise RuntimeError("notification requires a succeeded recovery execution")
    target = affected.target
    if target is None:
        raise RuntimeError("succeeded recovery execution is missing its target")
    task = await communications.create_recovery_notification(
        RecoveryCommunicationRequest(
            organization_id=command.organization_id,
            principal_id=command.principal_id,
            recipient_party_id=affected.subject_party_id,
            purpose=RecoveryCommunicationPurpose.RESCHEDULED,
            execution_id=execution.id,
            idempotency_key=f"recovery:{execution.id}:notification:v1",
            dedupe_key=f"operational-recovery:{execution.id}:rescheduled:v1",
            render_context={
                "reservation_id": str(command.reservation_id),
                "old_start_at": affected.original_start_at.isoformat(),
                "old_end_at": affected.original_end_at.isoformat(),
                "new_start_at": target.start_at.isoformat(),
                "new_end_at": target.end_at.isoformat(),
            },
        )
    )
    return await repository.attach_communication_task(
        organization_id=command.organization_id,
        execution_id=execution.id,
        communication_task_id=task.id,
    )
