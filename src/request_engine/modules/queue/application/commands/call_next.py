from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from request_engine.modules.queue.contracts.service_queue import QueueEntry


@dataclass(frozen=True, slots=True)
class CallNextCommand:
    organization_id: UUID
    principal_id: UUID
    queue_id: UUID
    idempotency_key: str


class CallNextExecutor(Protocol):
    async def call_next(self, command: CallNextCommand) -> QueueEntry | None: ...


async def call_next(
    executor: CallNextExecutor,
    command: CallNextCommand,
) -> QueueEntry | None:
    """Call the earliest eligible waiting entry from a FIFO service queue."""

    return await executor.call_next(command)
