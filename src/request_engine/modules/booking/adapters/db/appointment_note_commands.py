"""Booking-owned AddAppointmentNote over PostgreSQL.

READ     idempotency receipt (same key + same fingerprint replays the receipt).
LOCK     the Reservation row ``FOR KEY SHARE`` under tenant RLS: proves it exists
         in this tenant and keeps it visible; it does not conflict with lifecycle
         commands that update non-key Reservation columns, and no Resource or
         capacity root is touched (a note is not a capacity fact).
VALIDATE ``supersedes_note_id`` names a note of the same Reservation (the
         composite self-FK is the structural backstop).
WRITE    one immutable ``reservation_notes`` row; the author kind is read from the
         authoritative principal row, never from the caller (trigger backstop).
EMIT     audit + ``reservation.note_added.v1`` outbox fact without note text, so
         the change feed invalidates the day board without carrying PII.
"""

from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.booking.adapters.db.appointment_note_codec import (
    note_from_json,
    note_to_json,
)
from request_engine.modules.booking.application.commands.add_appointment_note import (
    AddAppointmentNoteCommand,
)
from request_engine.modules.booking.application.errors import (
    AppointmentNoteAuthorUnavailable,
    AppointmentNoteSupersedesUnknown,
    ReservationNotFound,
)
from request_engine.modules.booking.contracts.appointment_notes import AppointmentNote
from request_engine.platform.audit.postgres import append_audit
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)
from request_engine.platform.outbox.postgres import append_outbox

_CAPABILITY = "appointments.annotate"
NOTE_ADDED_EVENT = "reservation.note_added.v1"

_LOCK_RESERVATION = text(
    """
    SELECT id FROM request_engine.reservations
     WHERE organization_id = :organization_id AND id = :reservation_id
     FOR KEY SHARE
    """
)
_SUPERSEDED_EXISTS = text(
    """
    SELECT 1 FROM request_engine.reservation_notes
     WHERE organization_id = :organization_id
       AND reservation_id = :reservation_id
       AND id = :note_id
    """
)
_INSERT_NOTE = text(
    """
    INSERT INTO request_engine.reservation_notes
        (organization_id, reservation_id, body, author_principal_id,
         author_principal_kind, supersedes_note_id)
    SELECT :organization_id, :reservation_id, :body, p.id, p.principal_kind,
           :supersedes_note_id
      FROM request_engine.principals p
     WHERE p.organization_id = :organization_id AND p.id = :principal_id
    RETURNING id, author_principal_kind, created_at
    """
)
_AUTHOR_NAME = text(
    """
    SELECT author_display_name FROM request_read.reservation_notes_v1
     WHERE organization_id = :organization_id AND note_id = :note_id
    """
)


class PostgresAppointmentNoteCommands:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def add_appointment_note(self, command: AddAppointmentNoteCommand) -> AppointmentNote:
        fingerprint = command_fingerprint(
            _CAPABILITY,
            {
                "reservation_id": command.reservation_id,
                "body": command.body,
                "supersedes_note_id": command.supersedes_note_id,
            },
        )
        async with tenant_transaction(self._session_factory, command.organization_id) as session:
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability=_CAPABILITY,
                idempotency_key=command.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return note_from_json(cast(dict[str, object], replay["note"]))
            await _lock_and_validate(session, command)
            note = await _insert_note(session, command)
            await append_audit(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                command_name=_CAPABILITY,
                aggregate_kind="Reservation",
                aggregate_id=command.reservation_id,
                idempotency_id=idempotency_id,
                details={
                    "note_id": str(note.note_id),
                    "supersedes_note_id": _optional(note.supersedes_note_id),
                    "author_principal_kind": note.author_principal_kind,
                    "body_length": len(note.body),
                },
            )
            await append_outbox(
                session,
                organization_id=command.organization_id,
                event_type=NOTE_ADDED_EVENT,
                aggregate_kind="Reservation",
                aggregate_id=command.reservation_id,
                payload={
                    "reservation_id": str(command.reservation_id),
                    "note_id": str(note.note_id),
                    "author_principal_kind": note.author_principal_kind,
                    "supersedes_note_id": _optional(note.supersedes_note_id),
                },
            )
            await complete_idempotency(session, idempotency_id, {"note": note_to_json(note)})
            return note


async def _lock_and_validate(session: AsyncSession, command: AddAppointmentNoteCommand) -> None:
    locked = (
        await session.execute(
            _LOCK_RESERVATION,
            {"organization_id": command.organization_id, "reservation_id": command.reservation_id},
        )
    ).first()
    if locked is None:
        raise ReservationNotFound(command.reservation_id)
    if command.supersedes_note_id is None:
        return
    superseded = (
        await session.execute(
            _SUPERSEDED_EXISTS,
            {
                "organization_id": command.organization_id,
                "reservation_id": command.reservation_id,
                "note_id": command.supersedes_note_id,
            },
        )
    ).first()
    if superseded is None:
        raise AppointmentNoteSupersedesUnknown(command.reservation_id, command.supersedes_note_id)


async def _insert_note(
    session: AsyncSession, command: AddAppointmentNoteCommand
) -> AppointmentNote:
    row = (
        (
            await session.execute(
                _INSERT_NOTE,
                {
                    "organization_id": command.organization_id,
                    "reservation_id": command.reservation_id,
                    "body": command.body,
                    "principal_id": command.principal_id,
                    "supersedes_note_id": command.supersedes_note_id,
                },
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise AppointmentNoteAuthorUnavailable()
    note_id = cast(UUID, row["id"])
    display_name = (
        await session.execute(
            _AUTHOR_NAME, {"organization_id": command.organization_id, "note_id": note_id}
        )
    ).scalar_one_or_none()
    return AppointmentNote(
        note_id=note_id,
        reservation_id=command.reservation_id,
        body=command.body,
        author_principal_id=command.principal_id,
        author_principal_kind=cast(str, row["author_principal_kind"]),
        author_display_name=cast(str | None, display_name),
        supersedes_note_id=command.supersedes_note_id,
        created_at=cast(datetime, row["created_at"]),
    )


def _optional(value: UUID | None) -> str | None:
    return None if value is None else str(value)
