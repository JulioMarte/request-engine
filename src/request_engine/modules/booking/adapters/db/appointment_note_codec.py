from datetime import datetime
from typing import cast
from uuid import UUID

from request_engine.modules.booking.contracts.appointment_notes import AppointmentNote


def note_to_json(note: AppointmentNote) -> dict[str, object]:
    return {
        "note_id": str(note.note_id),
        "reservation_id": str(note.reservation_id),
        "body": note.body,
        "author_principal_id": str(note.author_principal_id),
        "author_principal_kind": note.author_principal_kind,
        "author_display_name": note.author_display_name,
        "supersedes_note_id": (
            None if note.supersedes_note_id is None else str(note.supersedes_note_id)
        ),
        "created_at": note.created_at.isoformat(),
    }


def note_from_json(data: dict[str, object]) -> AppointmentNote:
    supersedes = data.get("supersedes_note_id")
    return AppointmentNote(
        note_id=UUID(cast(str, data["note_id"])),
        reservation_id=UUID(cast(str, data["reservation_id"])),
        body=cast(str, data["body"]),
        author_principal_id=UUID(cast(str, data["author_principal_id"])),
        author_principal_kind=cast(str, data["author_principal_kind"]),
        author_display_name=cast(str | None, data.get("author_display_name")),
        supersedes_note_id=None if supersedes is None else UUID(cast(str, supersedes)),
        created_at=datetime.fromisoformat(cast(str, data["created_at"])),
    )
