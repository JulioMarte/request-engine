"""Append-only staff notes on a Reservation (Booking-owned read/receipt types)."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class AppointmentNote:
    note_id: UUID
    reservation_id: UUID
    body: str
    author_principal_id: UUID
    # The author Principal's kind (human, agent, integration, ...), recorded
    # from the authoritative principal row at write time.
    author_principal_kind: str
    # Staff profile or agent display name, resolved at read time; None when the
    # author has none (the receipt of a replay keeps the name seen at creation).
    author_display_name: str | None
    supersedes_note_id: UUID | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class LatestAppointmentNote:
    """Newest note of a Reservation, as an indicator (whitespace-collapsed excerpt)."""

    excerpt: str
    author_principal_kind: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class AppointmentNoteSummary:
    note_count: int
    latest: LatestAppointmentNote | None


@dataclass(frozen=True, slots=True)
class AppointmentNotePage:
    items: tuple[AppointmentNote, ...]
    has_more: bool
