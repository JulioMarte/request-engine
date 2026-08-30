from typing import cast

from request_engine.modules.operational_copilot.application.ports import RecoveryIntakeExecutor
from request_engine.modules.operational_copilot.contracts import CopilotExecutionReceipt
from request_engine.modules.operational_copilot.lowering.operations import CopilotOperation
from request_engine.modules.operational_recovery.contracts.workflow_commands import (
    SetRecoveryIntakeCommand,
)


class RecoveryIntakeCopilotExecutor:
    operation_type: type[object] = SetRecoveryIntakeCommand
    owner_capability = "operational_recovery.execute"

    def __init__(self, owner: RecoveryIntakeExecutor) -> None:
        self._owner = owner

    async def execute(self, operation: CopilotOperation) -> CopilotExecutionReceipt:
        command = cast(SetRecoveryIntakeCommand, operation)
        action = await self._owner.set_intake(command)
        return CopilotExecutionReceipt(
            action=str(action.action_kind.value),
            owner_action_id=action.id,
            incident_id=action.incident_id,
            status=str(action.status.value),
            idempotency_key=action.idempotency_key,
        )
