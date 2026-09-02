from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping

from request_engine.modules.booking.contracts.day_board import ReservationDayBoardEntry
from request_engine.platform.db.session import SessionFactory, tenant_transaction


class PostgresReservationDayBoardReader:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def read_window(
        self,
        organization_id: UUID,
        *,
        window_start: datetime,
        window_end: datetime,
    ) -> tuple[ReservationDayBoardEntry, ...]:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT reservation_id, offering_version_id, subject_party_id,
                               subject_display_name, location_id,
                               lower(during) AS start_at, upper(during) AS end_at,
                               status, revision, attendance_status,
                               attendance_responded_at, attendance_outcome,
                               attendance_outcome_at, estimated_arrival_at,
                               arrival_estimate_source_kind
                          FROM request_read.reservation_day_v1
                         WHERE organization_id = :organization_id
                           AND during && tstzrange(:window_start, :window_end, '[)')
                         ORDER BY lower(during), reservation_id
                        """
                    ),
                    {
                        "organization_id": organization_id,
                        "window_start": window_start,
                        "window_end": window_end,
                    },
                )
            ).mappings().all()
        return tuple(_entry_from_row(row) for row in rows)


def _entry_from_row(row: RowMapping) -> ReservationDayBoardEntry:
    return ReservationDayBoardEntry(
        reservation_id=cast(UUID, row["reservation_id"]),
        offering_version_id=cast(UUID, row["offering_version_id"]),
        subject_party_id=cast(UUID, row["subject_party_id"]),
        subject_display_name=cast(str, row["subject_display_name"]),
        location_id=cast(UUID | None, row["location_id"]),
        start_at=cast(datetime, row["start_at"]),
        end_at=cast(datetime, row["end_at"]),
        status=cast(str, row["status"]),
        revision=cast(int, row["revision"]),
        attendance_status=cast(str, row["attendance_status"]),
        attendance_responded_at=cast(datetime | None, row["attendance_responded_at"]),
        attendance_outcome=cast(str, row["attendance_outcome"]),
        attendance_outcome_at=cast(datetime | None, row["attendance_outcome_at"]),
        estimated_arrival_at=cast(datetime | None, row["estimated_arrival_at"]),
        arrival_estimate_source_kind=cast(str | None, row["arrival_estimate_source_kind"]),
    )
