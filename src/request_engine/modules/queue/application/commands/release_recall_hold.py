from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from request_engine.modules.queue.contracts.same_day_selection import RecallHold


@dataclass(frozen=True, slots=True)
class ReleaseRecallHoldCommand:
    organization_id: UUID
    principal_id: UUID
    queue_id: UUID
    queue_entry_id: UUID
    idempotency_key: str


class ReleaseRecallHoldExecutor(Protocol):
    async def release_recall_hold(
        self,
        command: ReleaseRecallHoldCommand,
    ) -> RecallHold | None: ...


async def release_recall_hold(
    executor: ReleaseRecallHoldExecutor,
    command: ReleaseRecallHoldCommand,
) -> RecallHold | None:
    return await executor.release_recall_hold(command)
