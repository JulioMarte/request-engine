from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class WaitlistEntryStatus(StrEnum):
    ACTIVE = "active"
    FULFILLED = "fulfilled"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class SlotOpportunityStatus(StrEnum):
    OPEN = "open"
    FILLED = "filled"
    CLOSED = "closed"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class WaitlistEntry:
    id: UUID
    offering_id: UUID
    subject_party_id: UUID
    location_id: UUID | None
    preferred_resource_id: UUID | None
    earliest_start: datetime | None
    latest_start: datetime | None
    status: WaitlistEntryStatus
    revision: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class SlotOpportunity:
    id: UUID
    offering_version_id: UUID
    location_id: UUID | None
    source_event_id: UUID
    source_reservation_id: UUID | None
    start_at: datetime
    end_at: datetime
    status: SlotOpportunityStatus
    revision: int
    created_at: datetime
