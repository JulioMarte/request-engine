from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from request_engine.modules.queue.contracts.service_queue import QueueEntry


@dataclass(frozen=True, slots=True)
class LeaveQueueCommand:
    organization_id: UUID
    principal_id: UUID
    queue_id: UUID
    subject_party_id: UUID
    idempotency_key: str
    reason: str | None = None
    allow_subject_override: bool = False


class LeaveQueueExecutor(Protocol):
    async def leave_queue(self, command: LeaveQueueCommand) -> QueueEntry: ...


async def leave_queue(executor: LeaveQueueExecutor, command: LeaveQueueCommand) -> QueueEntry:
    """Cancel the subject's waiting/called queue entry without affecting serving work."""

    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    if command.reason is not None and len(command.reason) > 1000:
        raise ValueError("reason must be at most 1000 characters")
    return await executor.leave_queue(command)
