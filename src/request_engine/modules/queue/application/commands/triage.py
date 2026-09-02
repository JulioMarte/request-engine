from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from request_engine.modules.queue.contracts.triage import (
    OperatorSelectReason,
    QueueTriageResult,
    RecallHoldKind,
    SkipReason,
)


@dataclass(frozen=True, slots=True)
class OperatorSelectCommand:
    organization_id: UUID
    principal_id: UUID
    queue_entry_id: UUID
    reason: OperatorSelectReason
    expected_revision: int
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class RecallHoldCommand:
    organization_id: UUID
    principal_id: UUID
    queue_entry_id: UUID
    condition_kind: RecallHoldKind
    expected_revision: int
    idempotency_key: str
    until_at: datetime | None = None
    event_key: str | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class SkipCommand:
    organization_id: UUID
    principal_id: UUID
    queue_entry_id: UUID
    reason: SkipReason
    expected_revision: int
    idempotency_key: str


class QueueTriageExecutor(Protocol):
    async def operator_select(self, command: OperatorSelectCommand) -> QueueTriageResult: ...

    async def recall_hold(self, command: RecallHoldCommand) -> QueueTriageResult: ...

    async def skip(self, command: SkipCommand) -> QueueTriageResult: ...
