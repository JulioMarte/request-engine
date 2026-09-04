from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ReservationDayBoardEntry:
    reservation_id: UUID
    offering_version_id: UUID
    subject_party_id: UUID
    subject_display_name: str
    location_id: UUID | None
    start_at: datetime
    end_at: datetime
    status: str
    revision: int
    attendance_status: str
    attendance_responded_at: datetime | None
    attendance_outcome: str
    attendance_outcome_at: datetime | None
    checked_in_at: datetime | None
    no_show_at: datetime | None
    reported_arrival_estimate_at: datetime | None
    effective_arrival_estimate_at: datetime | None
    estimated_arrival_at: datetime | None
    arrival_estimate_source_kind: str | None
    active_queue_entry_count: int
    queue_entry_id: UUID | None
    queue_entry_status: str | None
    recall_eligible: bool | None
    recall_hold_id: UUID | None
    recall_hold_kind: str | None
    recall_hold_until_at: datetime | None
    recall_hold_event_key: str | None
    recall_hold_reason: str | None
    active_skip_reason: str | None
