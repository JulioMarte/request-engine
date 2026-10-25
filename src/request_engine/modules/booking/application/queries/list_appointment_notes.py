"""Appointment note reads, gated by the staff read ``appointments.day_board``.

Notes are internal staff documentation: they are never served through the
subject-scoped ``appointments.read`` authority alone. Lists are newest first,
ordered by ``(created_at, note_id)`` descending; ``after`` continues strictly
after that position.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from request_engine.modules.booking.contracts.appointment_notes import (
    AppointmentNotePage,
    AppointmentNoteSummary,
)

MAX_NOTES_PAGE = 100
NOTES_READ_CAPABILITY = "appointments.day_board"


@dataclass(frozen=True, slots=True)
class NotePosition:
    created_at: datetime
    note_id: UUID


@dataclass(frozen=True, slots=True)
class AppointmentNotesQuery:
    organization_id: UUID
    reservation_id: UUID
    after: NotePosition | None
    limit: int


class AppointmentNoteReader(Protocol):
    async def list_notes(self, query: AppointmentNotesQuery) -> AppointmentNotePage | None:
        """Return the page, or None when the Reservation is not visible in the tenant."""
        ...

    async def summarize(
        self, organization_id: UUID, reservation_id: UUID
    ) -> AppointmentNoteSummary: ...
