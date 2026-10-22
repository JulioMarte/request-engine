from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class CalendarClaimedResource:
    """A Resource from the Reservation's current CapacityClaim set.

    ``claim_active`` is False once the claim was released in place (cancelled,
    declined or no-show); it then names the Resource the appointment was last
    planned on.
    """

    resource_id: UUID
    display_name: str
    claim_active: bool


@dataclass(frozen=True, slots=True)
class AppointmentCalendarEntry:
    reservation_id: UUID
    offering_version_id: UUID
    offering_display_name: str
    subject_party_id: UUID
    subject_display_name: str
    location_id: UUID | None
    start_at: datetime
    end_at: datetime
    status: str
    revision: int
    attendance_status: str
    attendance_outcome: str
    checked_in_at: datetime | None
    no_show_at: datetime | None
    visit_arrived_at: datetime | None
    served_queue_entry_id: UUID | None
    served_at: datetime | None
    resources: tuple[CalendarClaimedResource, ...]


@dataclass(frozen=True, slots=True)
class AppointmentCalendarPage:
    items: tuple[AppointmentCalendarEntry, ...]
    has_more: bool
