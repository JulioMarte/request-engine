from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from request_engine.modules.queue.contracts.waitlist import WaitlistEntry


@dataclass(frozen=True, slots=True)
class LeaveWaitlistCommand:
    organization_id: UUID
    principal_id: UUID
    waitlist_entry_id: UUID
    expected_revision: int
    idempotency_key: str
    reason: str | None = None
    allow_subject_override: bool = False


class LeaveWaitlistExecutor(Protocol):
    async def leave_waitlist(self, command: LeaveWaitlistCommand) -> WaitlistEntry: ...


async def leave_waitlist(
    executor: LeaveWaitlistExecutor,
    command: LeaveWaitlistCommand,
) -> WaitlistEntry:
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    if command.expected_revision <= 0:
        raise ValueError("expected_revision must be positive")
    return await executor.leave_waitlist(command)
