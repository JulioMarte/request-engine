from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from request_engine.modules.queue.contracts.same_day_selection import (
    RecallHold,
    RecallHoldKind,
    RecallHoldReason,
)


@dataclass(frozen=True, slots=True)
class RecallHoldCommand:
    organization_id: UUID
    principal_id: UUID
    queue_id: UUID
    queue_entry_id: UUID
    expected_revision: int
    kind: RecallHoldKind
    release_at: datetime | None
    reason: RecallHoldReason | None
    idempotency_key: str


class RecallHoldExecutor(Protocol):
    async def recall_hold(self, command: RecallHoldCommand) -> RecallHold: ...


async def recall_hold(
    executor: RecallHoldExecutor,
    command: RecallHoldCommand,
) -> RecallHold:
    return await executor.recall_hold(command)
