from typing import cast

from request_engine.modules.operational_copilot.application.ports import RecoveryCommandExecutor
from request_engine.modules.operational_copilot.contracts import CopilotExecutionReceipt
from request_engine.modules.operational_copilot.lowering.operations import CopilotOperation
from request_engine.modules.operational_recovery.contracts.commands import (
    CreateRecoveryProposalCommand,
    ExecuteRecoveryCommand,
)


class RecoveryProposalCopilotExecutor:
    operation_type: type[object] = CreateRecoveryProposalCommand
    owner_capability: str | None = "operational_recovery.propose"

    def __init__(self, owner: RecoveryCommandExecutor) -> None:
        self._owner = owner

    async def execute(self, operation: CopilotOperation) -> CopilotExecutionReceipt:
        command = cast(CreateRecoveryProposalCommand, operation)
        proposal = await self._owner.create_proposal(command)
        return CopilotExecutionReceipt(
            owner="operational_recovery",
            action="propose_recovery",
            result_id=proposal.id,
            status="created",
            idempotency_key=command.idempotency_key,
        )


class RecoveryExecutionCopilotExecutor:
    operation_type: type[object] = ExecuteRecoveryCommand
    owner_capability: str | None = "operational_recovery.execute"

    def __init__(self, owner: RecoveryCommandExecutor) -> None:
        self._owner = owner

    async def execute(self, operation: CopilotOperation) -> CopilotExecutionReceipt:
        command = cast(ExecuteRecoveryCommand, operation)
        execution = await self._owner.execute(command)
        return CopilotExecutionReceipt(
            owner="operational_recovery",
            action="execute_recovery",
            result_id=execution.id,
            status=str(execution.status.value),
            idempotency_key=command.idempotency_key,
        )
