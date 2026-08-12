from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class QueueEntryStatus(StrEnum):
    WAITING = "waiting"
    CALLED = "called"
    SERVING = "serving"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"


@dataclass(frozen=True, slots=True)
class QueueEntry:
    id: UUID
    queue_id: UUID
    subject_party_id: UUID
    status: QueueEntryStatus
    admitted_at: datetime
    called_at: datetime | None
    revision: int


@dataclass(frozen=True, slots=True)
class QueueStatus:
    queue_id: UUID
    queue_key: str
    display_name: str
    entry: QueueEntry | None
    entries_ahead: int | None
