from request_engine.modules.operational_recovery.application.workflow_intake_port import (
    RecoveryIntakeControlRequest,
    RecoveryIntakeControlResult,
)
from request_engine.modules.queue.contracts.intake import (
    QueueIntakeControlPort,
    SetQueueIntakeControlRequest,
)


class QueueRecoveryIntakeAdapter:
    def __init__(self, queue_intake: QueueIntakeControlPort) -> None:
        self._queue_intake = queue_intake

    async def set_recovery_intake_control(
        self,
        request: RecoveryIntakeControlRequest,
    ) -> RecoveryIntakeControlResult:
        current = await self._queue_intake.get_intake_control(
            request.organization_id,
            request.service_queue_id,
        )
        result = await self._queue_intake.set_intake_control(
            SetQueueIntakeControlRequest(
                organization_id=request.organization_id,
                principal_id=request.principal_id,
                service_queue_id=request.service_queue_id,
                accepting=request.accepting,
                expected_revision=current.revision,
                idempotency_key=request.idempotency_key,
                reason=request.reason,
                effective_until=request.effective_until,
            )
        )
        return RecoveryIntakeControlResult(
            service_queue_id=result.service_queue_id,
            revision=result.revision,
            accepting=result.accepting,
        )
