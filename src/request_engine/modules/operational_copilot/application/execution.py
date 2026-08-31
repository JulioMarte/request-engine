from request_engine.modules.operational_copilot.application.ports import CopilotMutationExecutor
from request_engine.modules.operational_copilot.contracts import CopilotExecutionReceipt
from request_engine.modules.operational_copilot.errors import UnsupportedCopilotIntent
from request_engine.modules.operational_copilot.lowering.operations import CopilotOperation


class CopilotExecutionRegistry:
    def __init__(self, executors: tuple[CopilotMutationExecutor, ...] = ()) -> None:
        self._executors = executors

    def owner_capability(self, operation: CopilotOperation) -> str | None:
        return self._resolve(operation).owner_capability

    async def execute(self, operation: CopilotOperation) -> CopilotExecutionReceipt:
        return await self._resolve(operation).execute(operation)

    def _resolve(self, operation: CopilotOperation) -> CopilotMutationExecutor:
        matches = tuple(
            executor
            for executor in self._executors
            if isinstance(operation, executor.operation_type)
        )
        if len(matches) != 1:
            raise UnsupportedCopilotIntent("copilot execution is not registered for this operation")
        return matches[0]
