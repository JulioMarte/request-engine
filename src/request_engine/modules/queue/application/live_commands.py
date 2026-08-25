from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from request_engine.modules.queue.contracts.live_queue import LiveQueueEntry


@dataclass(frozen=True, slots=True)
class CheckInCommand:
    organization_id: UUID
    principal_id: UUID
    queue_id: UUID
    subject_party_id: UUID
    idempotency_key: str
    reservation_id: UUID | None = None
    offering_id: UUID | None = None
    expected_workload_classification_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class MarkNoShowCommand:
    organization_id: UUID
    principal_id: UUID
    queue_entry_id: UUID
    expected_revision: int
    idempotency_key: str


class LiveQueueExecutor(Protocol):
    async def check_in(self, command: CheckInCommand) -> LiveQueueEntry: ...
    async def mark_no_show(self, command: MarkNoShowCommand) -> LiveQueueEntry: ...
