"""Appointment note body rules (Booking-owned, append-only staff notes).

A note is an immutable attributed fact on a Reservation. These rules are the
domain contract; PostgreSQL enforces the same shape as a structural backstop
(``reservation_notes_body_check``).
"""

import re

from request_engine.modules.booking.domain.errors import AppointmentNoteInvalid

MAX_NOTE_LENGTH = 1000
LATEST_NOTE_EXCERPT_LENGTH = 140

# Tab and line feed are legitimate inside a note; every other control
# character (including a bare carriage return) is not.
_FORBIDDEN_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def normalize_note_body(raw: str) -> str:
    """Return the canonical note text or raise ``AppointmentNoteInvalid``.

    Windows/old-Mac line endings become ``\n``; surrounding whitespace is
    trimmed; the result must hold 1..1000 characters (Unicode code points).
    """

    text = raw.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        raise AppointmentNoteInvalid("body must not be empty")
    if len(text) > MAX_NOTE_LENGTH:
        raise AppointmentNoteInvalid(f"body must be at most {MAX_NOTE_LENGTH} characters")
    if _FORBIDDEN_CONTROL.search(text):
        raise AppointmentNoteInvalid("body must not contain control characters")
    return text
