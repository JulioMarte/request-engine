"""Appointment note body rules and the command's validation boundary.

Protected risk: a note that is empty after trimming, longer than 1000
characters or carrying control characters must be refused before any handler
(database) call; legitimate multi-line notes and non-ASCII text must survive
unchanged apart from trimming and line-ending normalization. Plausible defects:
counting bytes instead of characters (rejecting accented text), not trimming,
rejecting newlines, forwarding the raw body to the handler.
"""

from dataclasses import dataclass, field
from uuid import uuid4

import pytest

from request_engine.modules.booking.application.commands.add_appointment_note import (
    AddAppointmentNoteCommand,
    add_appointment_note,
)
from request_engine.modules.booking.contracts.appointment_notes import AppointmentNote
from request_engine.modules.booking.domain.appointment_notes import (
    MAX_NOTE_LENGTH,
    normalize_note_body,
)
from request_engine.modules.booking.domain.errors import AppointmentNoteInvalid


def test_trims_and_keeps_multiline_unicode_text() -> None:
    assert normalize_note_body("  Viene con su hijo\t\n") == "Viene con su hijo"
    assert normalize_note_body("Pidió factura\r\ncon RNC\rok") == "Pidió factura\ncon RNC\nok"
    assert normalize_note_body("línea 1\n\tlínea 2") == "línea 1\n\tlínea 2"


def test_length_counts_characters_not_bytes() -> None:
    accented = "ñ" * MAX_NOTE_LENGTH  # 2000 UTF-8 bytes, 1000 characters
    assert normalize_note_body(accented) == accented
    with pytest.raises(AppointmentNoteInvalid) as too_long:
        normalize_note_body("a" * (MAX_NOTE_LENGTH + 1))
    assert "1000" in too_long.value.reason


@pytest.mark.parametrize("raw", ["", "   ", "\n\t \r\n"])
def test_empty_after_trimming_is_rejected(raw: str) -> None:
    with pytest.raises(AppointmentNoteInvalid):
        normalize_note_body(raw)


@pytest.mark.parametrize("raw", ["bell\x07", "nul\x00x", "esc\x1b[0m", "del\x7f", "vt\x0bx"])
def test_control_characters_are_rejected(raw: str) -> None:
    with pytest.raises(AppointmentNoteInvalid):
        normalize_note_body(raw)


@dataclass
class _RecordingHandler:
    received: list[AddAppointmentNoteCommand] = field(
        default_factory=lambda: list[AddAppointmentNoteCommand]()
    )

    async def add_appointment_note(self, command: AddAppointmentNoteCommand) -> AppointmentNote:
        self.received.append(command)
        raise _Sentinel


class _Sentinel(Exception):
    """Stops after the handler boundary; persistence is proven by the PostgreSQL suite."""


def _command(body: str, key: str = "k-1") -> AddAppointmentNoteCommand:
    return AddAppointmentNoteCommand(
        organization_id=uuid4(),
        principal_id=uuid4(),
        reservation_id=uuid4(),
        body=body,
        idempotency_key=key,
    )


@pytest.mark.asyncio
async def test_command_forwards_only_the_normalized_body() -> None:
    handler = _RecordingHandler()
    with pytest.raises(_Sentinel):
        await add_appointment_note(handler, _command("  Llega 10 min tarde \r\n"))
    assert [item.body for item in handler.received] == ["Llega 10 min tarde"]


@pytest.mark.asyncio
async def test_invalid_command_never_reaches_the_handler() -> None:
    handler = _RecordingHandler()
    with pytest.raises(AppointmentNoteInvalid):
        await add_appointment_note(handler, _command("   "))
    with pytest.raises(ValueError, match="idempotency_key"):
        await add_appointment_note(handler, _command("ok", key=""))
    assert handler.received == []
