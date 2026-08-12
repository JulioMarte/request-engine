from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from request_engine.modules.queue.contracts.service_queue import QueueEntry


@dataclass(frozen=True, slots=True)
class JoinQueueCommand:
    organization_id: UUID
    principal_id: UUID
    queue_id: UUID
    subject_party_id: UUID
    idempotency_key: str
    reservation_id: UUID | None = None
    offering_id: UUID | None = None


class JoinQueueExecutor(Protocol):
    async def join_queue(self, command: JoinQueueCommand) -> QueueEntry: ...


async def join_queue(executor: JoinQueueExecutor, command: JoinQueueCommand) -> QueueEntry:
    """Join an active FIFO service queue exactly once for this command identity."""

    return await executor.join_queue(command)
