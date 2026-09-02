from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from request_engine.modules.queue.contracts.same_day_selection import SkipReason, SkipResult


@dataclass(frozen=True, slots=True)
class SkipQueueHeadCommand:
    organization_id: UUID
    principal_id: UUID
    queue_id: UUID
    reason: SkipReason
    idempotency_key: str


class SkipQueueHeadExecutor(Protocol):
    async def skip_queue_head(self, command: SkipQueueHeadCommand) -> SkipResult | None: ...


async def skip_queue_head(
    executor: SkipQueueHeadExecutor,
    command: SkipQueueHeadCommand,
) -> SkipResult | None:
    return await executor.skip_queue_head(command)
