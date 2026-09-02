from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping

from request_engine.modules.booking.application.queries.get_day_board import GetDayBoardQuery
from request_engine.modules.booking.contracts.day_board import DayBoardEntry
from request_engine.platform.db.session import SessionFactory, tenant_transaction


class PostgresDayBoardReader:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def get_day_board(self, query: GetDayBoardQuery) -> tuple[DayBoardEntry, ...]:
        async with tenant_transaction(self._session_factory, query.organization_id) as session:
            rows = (
                (
                    await session.execute(
                        text(
                            """
                        SELECT reservation_id, subject_party_id, subject_display_name,
                               offering_version_id, location_id,
                               lower(during) AS start_at, upper(during) AS end_at,
                               status, revision, attendance_status,
                               attendance_responded_at, attendance_outcome_status,
                               checked_in_at, no_show_at, reported_arrival_estimate_at,
                               effective_arrival_estimate_at, arrival_estimate_source_kind
                        FROM request_read.reservation_day_v1
                        WHERE organization_id = :organization_id
                          AND during && tstzrange(:window_start, :window_end, '[)')
                          AND (:location_id IS NULL OR location_id = :location_id)
                        ORDER BY lower(during), reservation_id
                        LIMIT :limit
                        """
                        ),
                        {
                            "organization_id": query.organization_id,
                            "window_start": query.window_start,
                            "window_end": query.window_end,
                            "location_id": query.location_id,
                            "limit": query.limit,
                        },
                    )
                )
                .mappings()
                .all()
            )
        return tuple(_entry_from_row(row) for row in rows)


def _entry_from_row(row: RowMapping) -> DayBoardEntry:
    return DayBoardEntry(
        reservation_id=cast(UUID, row["reservation_id"]),
        subject_party_id=cast(UUID, row["subject_party_id"]),
        subject_display_name=cast(str, row["subject_display_name"]),
        offering_version_id=cast(UUID, row["offering_version_id"]),
        location_id=cast(UUID | None, row["location_id"]),
        start_at=cast(datetime, row["start_at"]),
        end_at=cast(datetime, row["end_at"]),
        reservation_status=cast(str, row["status"]),
        reservation_revision=cast(int, row["revision"]),
        attendance_status=cast(str, row["attendance_status"]),
        attendance_responded_at=cast(datetime | None, row["attendance_responded_at"]),
        attendance_outcome_status=cast(str, row["attendance_outcome_status"]),
        checked_in_at=cast(datetime | None, row["checked_in_at"]),
        no_show_at=cast(datetime | None, row["no_show_at"]),
        reported_arrival_estimate_at=cast(datetime | None, row["reported_arrival_estimate_at"]),
        effective_arrival_estimate_at=cast(datetime | None, row["effective_arrival_estimate_at"]),
        arrival_estimate_source_kind=cast(str | None, row["arrival_estimate_source_kind"]),
    )
