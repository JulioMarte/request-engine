"""Append-only staff notes on an appointment (Booking owner).

``POST /v1/appointments/{reservation_id}/notes`` — ``appointments_note_add``,
capability ``appointments.annotate`` (operator, low-impact write, Idempotency-Key
required, no expected revision: a note never changes the Reservation revision).

``GET /v1/appointments/{reservation_id}/notes`` — ``appointments_notes_list``,
capability ``appointments.day_board`` (the staff appointment read; notes are
internal and never served through subject-scoped ``appointments.read`` alone).
Newest first, opaque keyset cursor bound to the Reservation.
"""

import base64
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError

from request_engine.modules.booking.api.dependencies import IdempotencyKey
from request_engine.modules.booking.application import errors as booking_errors
from request_engine.modules.booking.application.commands.add_appointment_note import (
    AddAppointmentNoteCommand,
    AddAppointmentNoteHandler,
    add_appointment_note,
)
from request_engine.modules.booking.application.queries.list_appointment_notes import (
    MAX_NOTES_PAGE,
    NOTES_READ_CAPABILITY,
    AppointmentNoteReader,
    AppointmentNotesQuery,
    NotePosition,
)
from request_engine.modules.booking.contracts.appointment_notes import AppointmentNote
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, require_capability


class AppointmentNoteBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(
        min_length=1,
        max_length=4000,
        description="Note text; trimmed, then 1..1000 characters. Tab and newline allowed.",
    )
    supersedes_note_id: UUID | None = Field(
        default=None,
        description="Optional earlier note of the same appointment that this note corrects.",
    )


class AppointmentNoteView(BaseModel):
    note_id: UUID
    reservation_id: UUID
    body: str
    author_principal_id: UUID
    author_kind: str
    author_display_name: str | None
    supersedes_note_id: UUID | None
    created_at: datetime

    @classmethod
    def from_contract(cls, note: AppointmentNote) -> "AppointmentNoteView":
        return cls(
            note_id=note.note_id,
            reservation_id=note.reservation_id,
            body=note.body,
            author_principal_id=note.author_principal_id,
            author_kind=note.author_principal_kind,
            author_display_name=note.author_display_name,
            supersedes_note_id=note.supersedes_note_id,
            created_at=note.created_at,
        )


class AppointmentNotePageView(BaseModel):
    items: tuple[AppointmentNoteView, ...]
    next_cursor: str | None


class _NoteCursorParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reservation_id: UUID
    created_at: AwareDatetime
    note_id: UUID


def _decode_cursor(cursor: str, reservation_id: UUID) -> NotePosition:
    try:
        value = _NoteCursorParams.model_validate_json(
            base64.b64decode(cursor, altchars=b"-_", validate=True)
        )
    except (ValueError, ValidationError):
        raise HTTPException(status_code=422, detail="cursor is invalid") from None
    if value.reservation_id != reservation_id:
        raise HTTPException(status_code=422, detail="cursor does not match this appointment")
    return NotePosition(created_at=value.created_at, note_id=value.note_id)


def _encode_cursor(last: AppointmentNote) -> str:
    value = _NoteCursorParams(
        reservation_id=last.reservation_id, created_at=last.created_at, note_id=last.note_id
    )
    return base64.urlsafe_b64encode(value.model_dump_json().encode()).decode()


def add_appointment_note_routes(
    router: APIRouter,
    handler: AddAppointmentNoteHandler,
    reader: AppointmentNoteReader,
    actor_resolver: ActorResolver,
) -> None:
    async def authenticated_actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def add_note(
        reservation_id: UUID,
        body: AppointmentNoteBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
    ) -> AppointmentNoteView:
        require_capability(actor, "appointments.annotate")
        note = await add_appointment_note(
            handler,
            AddAppointmentNoteCommand(
                organization_id=actor.organization_id,
                principal_id=actor.principal_id,
                reservation_id=reservation_id,
                body=body.body,
                supersedes_note_id=body.supersedes_note_id,
                idempotency_key=idempotency_key,
            ),
        )
        return AppointmentNoteView.from_contract(note)

    async def list_notes(
        reservation_id: UUID,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        after: Annotated[
            str | None,
            Query(max_length=512, description="Pass next_cursor from the previous page"),
        ] = None,
        limit: Annotated[int, Query(ge=1, le=MAX_NOTES_PAGE)] = 50,
    ) -> AppointmentNotePageView:
        require_capability(actor, NOTES_READ_CAPABILITY)
        page = await reader.list_notes(
            AppointmentNotesQuery(
                organization_id=actor.organization_id,
                reservation_id=reservation_id,
                after=_decode_cursor(after, reservation_id) if after is not None else None,
                limit=limit,
            )
        )
        if page is None:
            raise booking_errors.ReservationNotFound(reservation_id)
        return AppointmentNotePageView(
            items=tuple(AppointmentNoteView.from_contract(item) for item in page.items),
            next_cursor=_encode_cursor(page.items[-1]) if page.has_more and page.items else None,
        )

    add_capability_route(
        router,
        "/{reservation_id}/notes",
        add_note,
        capability="appointments.annotate",
        methods=["POST"],
        operation_id="appointments_note_add",
        tool_name="appointments_note_add",
        tool_audiences=("operator",),
        summary="Add a note to an appointment",
        description=(
            "Append an internal staff note to an appointment (for example 'comes with her "
            "son' or 'asked for an invoice with RNC'). Notes are immutable: to correct one, "
            "add a new note with supersedes_note_id. Works on cancelled appointments too."
        ),
        response_model=AppointmentNoteView,
        status_code=status.HTTP_201_CREATED,
    )
    add_capability_route(
        router,
        "/{reservation_id}/notes",
        list_notes,
        capability=NOTES_READ_CAPABILITY,
        methods=["GET"],
        operation_id="appointments_notes_list",
        tool_name="appointments_notes_list",
        tool_audiences=("operator",),
        summary="List an appointment's notes",
        description=(
            "List the internal staff notes of one appointment, newest first, with author "
            "kind and display name. Page with next_cursor."
        ),
        response_model=AppointmentNotePageView,
    )
