from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class LiveQueueEntry:
    id: UUID
    queue_id: UUID
    subject_party_id: UUID
    reservation_id: UUID | None
    offering_id: UUID | None
    status: str
    arrived_at: datetime
    admitted_at: datetime
    called_at: datetime | None
    expected_workload_classification_id: UUID | None
    revision: int


@dataclass(frozen=True, slots=True)
class StaffQueueEntry:
    queue_entry_id: UUID
    queue_id: UUID
    subject_party_id: UUID
    subject_display_name: str
    reservation_id: UUID | None
    status: str
    scheduled_at: datetime | None
    arrived_at: datetime
    admitted_at: datetime
    called_at: datetime | None
    expected_workload_key: str | None
    service_session_id: UUID | None
    service_status: str | None
    actual_resource_id: UUID | None
    actual_location_id: UUID | None
    actual_workload_key: str | None
    service_started_at: datetime | None
    service_completed_at: datetime | None
    recall_hold_kind: str | None
    recall_hold_release_at: datetime | None
    queue_revision: int
    service_revision: int | None


@dataclass(frozen=True, slots=True)
class StaffQueueHistoryPage:
    entries: tuple[StaffQueueEntry, ...]
    next_cursor: UUID | None


@dataclass(frozen=True, slots=True)
class WorkloadClassification:
    id: UUID
    workload_key: str
    display_name: str
    active: bool
    revision: int
