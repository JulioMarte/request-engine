"""AddAppointmentNote: append one attributed staff note to a Reservation.

A semantic Command (capability ``appointments.annotate``), not an edit: notes
are immutable and a correction is a new note naming ``supersedes_note_id``.
Any Reservation status is accepted (staff may document a cancellation). A note
never changes the Reservation revision, so it cannot invalidate a concurrent
reschedule/cancel that carries an expected revision.
"""

from dataclasses import dataclass, replace
from typing import Protocol
from uuid import UUID

from request_engine.modules.booking.contracts.appointment_notes import AppointmentNote
from request_engine.modules.booking.domain.appointment_notes import normalize_note_body


@dataclass(frozen=True, slots=True)
class AddAppointmentNoteCommand:
    organization_id: UUID
    principal_id: UUID
    reservation_id: UUID
    body: str
    idempotency_key: str
    supersedes_note_id: UUID | None = None


class AddAppointmentNoteHandler(Protocol):
    async def add_appointment_note(self, command: AddAppointmentNoteCommand) -> AppointmentNote: ...


async def add_appointment_note(
    handler: AddAppointmentNoteHandler,
    command: AddAppointmentNoteCommand,
) -> AppointmentNote:
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    return await handler.add_appointment_note(
        replace(command, body=normalize_note_body(command.body))
    )
