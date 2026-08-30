from typing import cast

from request_engine.modules.operational_copilot.application.ports import RecoveryExtendDayExecutor
from request_engine.modules.operational_copilot.contracts import CopilotExecutionReceipt
from request_engine.modules.operational_copilot.lowering.operations import CopilotOperation
from request_engine.modules.operational_recovery.contracts.workflow_commands import (
    ExtendRecoveryDayCommand,
)


class RecoveryExtendDayCopilotExecutor:
    operation_type: type[object] = ExtendRecoveryDayCommand
    owner_capability = "operational_recovery.execute"

    def __init__(self, owner: RecoveryExtendDayExecutor) -> None:
        self._owner = owner

    async def execute(self, operation: CopilotOperation) -> CopilotExecutionReceipt:
        command = cast(ExtendRecoveryDayCommand, operation)
        action = await self._owner.extend_day(command)
        return CopilotExecutionReceipt(
            action=str(action.action_kind.value),
            owner_action_id=action.id,
            incident_id=action.incident_id,
            status=str(action.status.value),
            idempotency_key=action.idempotency_key,
        )
