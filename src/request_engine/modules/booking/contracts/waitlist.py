from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from request_engine.modules.booking.contracts.appointments import Reservation


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


class SlotOfferStatus(StrEnum):
    OFFERED = "offered"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


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
    created_at: datetime
    revision: int


@dataclass(frozen=True, slots=True)
class SlotOpportunity:
    id: UUID
    offering_version_id: UUID
    location_id: UUID | None
    source_reservation_id: UUID | None
    source_event_id: UUID
    start_at: datetime
    end_at: datetime
    status: SlotOpportunityStatus
    revision: int


@dataclass(frozen=True, slots=True)
class SlotOffer:
    id: UUID
    slot_opportunity_id: UUID
    waitlist_entry_id: UUID
    capacity_hold_id: UUID
    expires_at: datetime
    status: SlotOfferStatus
    revision: int


@dataclass(frozen=True, slots=True)
class AcceptedSlotOffer:
    offer: SlotOffer
    reservation: Reservation
