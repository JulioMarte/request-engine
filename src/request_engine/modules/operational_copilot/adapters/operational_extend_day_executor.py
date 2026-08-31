from typing import cast

from request_engine.modules.booking.contracts.operational_schedule import (
    OperationalAssignmentExtensionRequest,
    OperationalAssignmentRevisionConflict,
    OperationalAssignmentSchedulePort,
)
from request_engine.modules.operational_copilot.contracts import CopilotExecutionReceipt
from request_engine.modules.operational_copilot.errors import CopilotConflict
from request_engine.modules.operational_copilot.lowering.operations import CopilotOperation


class OperationalExtendDayCopilotExecutor:
    operation_type: type[object] = OperationalAssignmentExtensionRequest
    owner_capability: str | None = "booking.manage_supply"

    def __init__(self, owner: OperationalAssignmentSchedulePort) -> None:
        self._owner = owner

    async def execute(self, operation: CopilotOperation) -> CopilotExecutionReceipt:
        request = cast(OperationalAssignmentExtensionRequest, operation)
        try:
            state = await self._owner.extend_assignment_hours(request)
        except OperationalAssignmentRevisionConflict as error:
            raise CopilotConflict(str(error)) from error
        return CopilotExecutionReceipt(
            owner="booking",
            action="extend_assignment_hours",
            result_id=state.exception_id,
            status="applied",
            idempotency_key=request.idempotency_key,
        )
