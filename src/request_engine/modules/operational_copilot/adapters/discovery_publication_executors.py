from typing import cast

from request_engine.modules.discovery.contracts.commands import (
    PublishDiscoverySupplyCommand,
    RevokeDiscoveryPublicationCommand,
)
from request_engine.modules.operational_copilot.application.ports import (
    DiscoveryPublicationExecutor,
)
from request_engine.modules.operational_copilot.contracts import CopilotExecutionReceipt
from request_engine.modules.operational_copilot.lowering.operations import CopilotOperation


class DiscoveryPublishCopilotExecutor:
    operation_type: type[object] = PublishDiscoverySupplyCommand
    owner_capability: str | None = None

    def __init__(self, owner: DiscoveryPublicationExecutor) -> None:
        self._owner = owner

    async def execute(self, operation: CopilotOperation) -> CopilotExecutionReceipt:
        command = cast(PublishDiscoverySupplyCommand, operation)
        state = await self._owner.publish(command)
        return CopilotExecutionReceipt(
            owner="discovery",
            action="publish_discovery_supply",
            result_id=state.id,
            status=state.status,
            idempotency_key=command.idempotency_key,
        )


class DiscoveryRevokeCopilotExecutor:
    operation_type: type[object] = RevokeDiscoveryPublicationCommand
    owner_capability: str | None = None

    def __init__(self, owner: DiscoveryPublicationExecutor) -> None:
        self._owner = owner

    async def execute(self, operation: CopilotOperation) -> CopilotExecutionReceipt:
        command = cast(RevokeDiscoveryPublicationCommand, operation)
        state = await self._owner.revoke(command)
        return CopilotExecutionReceipt(
            owner="discovery",
            action="revoke_discovery_publication",
            result_id=state.id,
            status=state.status,
            idempotency_key=command.idempotency_key,
        )
