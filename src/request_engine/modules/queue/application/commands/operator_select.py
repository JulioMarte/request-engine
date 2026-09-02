from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from request_engine.modules.queue.contracts.same_day_selection import OperatorSelectReason
from request_engine.modules.queue.contracts.service_queue import QueueEntry


@dataclass(frozen=True, slots=True)
class OperatorSelectCommand:
    organization_id: UUID
    principal_id: UUID
    queue_id: UUID
    queue_entry_id: UUID
    reason: OperatorSelectReason
    idempotency_key: str


class OperatorSelectExecutor(Protocol):
    async def operator_select(self, command: OperatorSelectCommand) -> QueueEntry: ...


async def operator_select(
    executor: OperatorSelectExecutor,
    command: OperatorSelectCommand,
) -> QueueEntry:
    return await executor.operator_select(command)
