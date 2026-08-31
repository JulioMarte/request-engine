from typing import cast

from request_engine.modules.operational_copilot.contracts import CopilotExecutionReceipt
from request_engine.modules.operational_copilot.lowering.operations import CopilotOperation
from request_engine.modules.queue.contracts.intake import (
    QueueIntakeControlPort,
    SetQueueIntakeControlRequest,
)


class OperationalIntakeCopilotExecutor:
    operation_type: type[object] = SetQueueIntakeControlRequest
    owner_capability: str | None = "queue.manage_intake"

    def __init__(self, owner: QueueIntakeControlPort) -> None:
        self._owner = owner

    async def execute(self, operation: CopilotOperation) -> CopilotExecutionReceipt:
        request = cast(SetQueueIntakeControlRequest, operation)
        state = await self._owner.set_intake_control(request)
        return CopilotExecutionReceipt(
            owner="queue",
            action="set_intake_control",
            result_id=state.service_queue_id,
            status="applied",
            idempotency_key=request.idempotency_key,
        )
