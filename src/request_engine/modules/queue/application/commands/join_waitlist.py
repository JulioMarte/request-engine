from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from request_engine.modules.queue.contracts.waitlist import WaitlistEntry


@dataclass(frozen=True, slots=True)
class JoinWaitlistCommand:
    organization_id: UUID
    principal_id: UUID
    offering_id: UUID
    subject_party_id: UUID
    idempotency_key: str
    location_id: UUID | None = None
    preferred_resource_id: UUID | None = None
    earliest_start: datetime | None = None
    latest_start: datetime | None = None
    allow_subject_override: bool = False


class JoinWaitlistExecutor(Protocol):
    async def join_waitlist(self, command: JoinWaitlistCommand) -> WaitlistEntry: ...


async def join_waitlist(
    executor: JoinWaitlistExecutor,
    command: JoinWaitlistCommand,
) -> WaitlistEntry:
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    if (
        command.earliest_start is not None
        and command.latest_start is not None
        and command.latest_start < command.earliest_start
    ):
        raise ValueError("latest_start must be greater than or equal to earliest_start")
    return await executor.join_waitlist(command)
