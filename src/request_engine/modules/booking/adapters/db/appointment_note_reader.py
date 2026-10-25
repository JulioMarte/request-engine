from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping

from request_engine.modules.booking.application.queries.list_appointment_notes import (
    AppointmentNotesQuery,
)
from request_engine.modules.booking.contracts.appointment_notes import (
    AppointmentNote,
    AppointmentNotePage,
    AppointmentNoteSummary,
    LatestAppointmentNote,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction

_RESERVATION_VISIBLE = text(
    """
    SELECT 1 FROM request_read.reservation_status_v1
     WHERE organization_id = :organization_id AND reservation_id = :reservation_id
    """
)
_LIST_NOTES = text(
    """
    SELECT note_id, reservation_id, body, author_principal_id, author_principal_kind,
           author_display_name, supersedes_note_id, created_at
      FROM request_read.reservation_notes_v1
     WHERE organization_id = :organization_id
       AND reservation_id = :reservation_id
       AND (CAST(:after_created AS timestamptz) IS NULL
            OR (created_at, note_id)
               < (CAST(:after_created AS timestamptz), CAST(:after_id AS uuid)))
     ORDER BY created_at DESC, note_id DESC
     LIMIT :fetch
    """
)
# Same excerpt expression as request_read.reservation_day_v1.latest_note_excerpt.
_SUMMARY = text(
    r"""
    SELECT (SELECT count(*)::integer FROM request_read.reservation_notes_v1 counted
             WHERE counted.organization_id = :organization_id
               AND counted.reservation_id = :reservation_id) AS note_count,
           latest.excerpt, latest.author_principal_kind, latest.created_at
      FROM (SELECT 1) AS one
      LEFT JOIN LATERAL (
            SELECT "left"(regexp_replace(n.body, '\s+', ' ', 'g'), 140) AS excerpt,
                   n.author_principal_kind, n.created_at
              FROM request_read.reservation_notes_v1 n
             WHERE n.organization_id = :organization_id
               AND n.reservation_id = :reservation_id
             ORDER BY n.created_at DESC, n.note_id DESC
             LIMIT 1
           ) latest ON true
    """
)


class PostgresAppointmentNoteReader:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def list_notes(self, query: AppointmentNotesQuery) -> AppointmentNotePage | None:
        identity = {
            "organization_id": query.organization_id,
            "reservation_id": query.reservation_id,
        }
        after = query.after
        async with tenant_transaction(self._session_factory, query.organization_id) as session:
            if (await session.execute(_RESERVATION_VISIBLE, identity)).first() is None:
                return None
            rows = (
                (
                    await session.execute(
                        _LIST_NOTES,
                        {
                            **identity,
                            "after_created": after.created_at if after else None,
                            "after_id": after.note_id if after else None,
                            "fetch": query.limit + 1,
                        },
                    )
                )
                .mappings()
                .all()
            )
        return AppointmentNotePage(
            items=tuple(note_from_row(row) for row in rows[: query.limit]),
            has_more=len(rows) > query.limit,
        )

    async def summarize(
        self, organization_id: UUID, reservation_id: UUID
    ) -> AppointmentNoteSummary:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            row = (
                (
                    await session.execute(
                        _SUMMARY,
                        {"organization_id": organization_id, "reservation_id": reservation_id},
                    )
                )
                .mappings()
                .one()
            )
        return summary_from_columns(
            cast(int, row["note_count"]),
            cast(str | None, row["excerpt"]),
            cast(str | None, row["author_principal_kind"]),
            cast(datetime | None, row["created_at"]),
        )


def note_from_row(row: RowMapping) -> AppointmentNote:
    return AppointmentNote(
        note_id=cast(UUID, row["note_id"]),
        reservation_id=cast(UUID, row["reservation_id"]),
        body=cast(str, row["body"]),
        author_principal_id=cast(UUID, row["author_principal_id"]),
        author_principal_kind=cast(str, row["author_principal_kind"]),
        author_display_name=cast(str | None, row["author_display_name"]),
        supersedes_note_id=cast(UUID | None, row["supersedes_note_id"]),
        created_at=cast(datetime, row["created_at"]),
    )


def summary_from_columns(
    note_count: int,
    excerpt: str | None,
    author_kind: str | None,
    created_at: datetime | None,
) -> AppointmentNoteSummary:
    latest = (
        LatestAppointmentNote(
            excerpt=excerpt, author_principal_kind=author_kind, created_at=created_at
        )
        if excerpt is not None and author_kind is not None and created_at is not None
        else None
    )
    return AppointmentNoteSummary(note_count=note_count, latest=latest)
