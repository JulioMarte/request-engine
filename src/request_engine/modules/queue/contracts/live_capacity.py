from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from request_engine.platform.db.read_snapshot_types import ReadSnapshot


@dataclass(frozen=True, slots=True)
class QueueProjectionEntry:
    queue_entry_id: UUID
    queue_id: UUID
    reservation_id: UUID | None
    status: str
    arrived_at: datetime
    admitted_at: datetime
    called_at: datetime | None
    expected_workload_classification_id: UUID | None


@dataclass(frozen=True, slots=True)
class QueueProjectionSnapshot:
    queue_id: UUID
    observed_at: datetime
    entries: tuple[QueueProjectionEntry, ...]
    completed_reservation_ids: frozenset[UUID] = frozenset()


@dataclass(frozen=True, slots=True)
class CustomerQueueProjectionTarget:
    queue_entry_id: UUID
    entries_ahead: int


class QueueProjectionSource(Protocol):
    async def read_projection_queue(
        self,
        snapshot: ReadSnapshot,
        *,
        organization_id: UUID,
        queue_id: UUID,
        observed_at: datetime,
        relevant_reservation_ids: tuple[UUID, ...] = (),
    ) -> QueueProjectionSnapshot: ...

    async def read_customer_projection_target(
        self,
        snapshot: ReadSnapshot,
        *,
        organization_id: UUID,
        principal_id: UUID,
        queue_id: UUID,
        subject_party_id: UUID,
        allow_subject_override: bool,
    ) -> CustomerQueueProjectionTarget | None: ...
