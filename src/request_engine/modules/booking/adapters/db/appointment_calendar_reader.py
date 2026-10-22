from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping

from request_engine.modules.booking.application.queries.get_appointment_calendar import (
    AppointmentCalendarQuery,
)
from request_engine.modules.booking.contracts.appointment_calendar import (
    AppointmentCalendarEntry,
    AppointmentCalendarPage,
    CalendarClaimedResource,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction

_CALENDAR_SQL = """
SELECT reservation_id, offering_version_id, offering_display_name,
       subject_party_id, subject_display_name, location_id,
       lower(during) AS start_at, upper(during) AS end_at,
       status, revision, attendance_status, attendance_outcome,
       checked_in_at, no_show_at, visit_arrived_at,
       served_queue_entry_id, served_at, claimed_resources
  FROM request_read.reservation_calendar_v1
 WHERE organization_id = :organization_id
   AND during && tstzrange(:window_start, :window_end, '[)')
   AND (CAST(:location_id AS uuid) IS NULL OR location_id = CAST(:location_id AS uuid))
   AND (CAST(:resource_id AS uuid) IS NULL
        OR claimed_resource_ids @> ARRAY[CAST(:resource_id AS uuid)])
   AND (CAST(:after_start AS timestamptz) IS NULL
        OR (lower(during), reservation_id)
           > (CAST(:after_start AS timestamptz), CAST(:after_id AS uuid)))
 ORDER BY lower(during), reservation_id
 LIMIT :fetch
"""


class PostgresAppointmentCalendarReader:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def read_calendar(self, query: AppointmentCalendarQuery) -> AppointmentCalendarPage:
        after = query.after
        async with tenant_transaction(self._session_factory, query.organization_id) as session:
            rows = (
                (
                    await session.execute(
                        text(_CALENDAR_SQL),
                        {
                            "organization_id": query.organization_id,
                            "window_start": query.window_start,
                            "window_end": query.window_end,
                            "location_id": query.location_id,
                            "resource_id": query.resource_id,
                            "after_start": after.start_at if after else None,
                            "after_id": after.reservation_id if after else None,
                            "fetch": query.limit + 1,
                        },
                    )
                )
                .mappings()
                .all()
            )
        return AppointmentCalendarPage(
            items=tuple(_entry(row) for row in rows[: query.limit]),
            has_more=len(rows) > query.limit,
        )


def _entry(row: RowMapping) -> AppointmentCalendarEntry:
    claimed = cast(list[dict[str, object]], row["claimed_resources"])
    return AppointmentCalendarEntry(
        reservation_id=cast(UUID, row["reservation_id"]),
        offering_version_id=cast(UUID, row["offering_version_id"]),
        offering_display_name=cast(str, row["offering_display_name"]),
        subject_party_id=cast(UUID, row["subject_party_id"]),
        subject_display_name=cast(str, row["subject_display_name"]),
        location_id=cast(UUID | None, row["location_id"]),
        start_at=cast(datetime, row["start_at"]),
        end_at=cast(datetime, row["end_at"]),
        status=cast(str, row["status"]),
        revision=cast(int, row["revision"]),
        attendance_status=cast(str, row["attendance_status"]),
        attendance_outcome=cast(str, row["attendance_outcome"]),
        checked_in_at=cast(datetime | None, row["checked_in_at"]),
        no_show_at=cast(datetime | None, row["no_show_at"]),
        visit_arrived_at=cast(datetime | None, row["visit_arrived_at"]),
        served_queue_entry_id=cast(UUID | None, row["served_queue_entry_id"]),
        served_at=cast(datetime | None, row["served_at"]),
        resources=tuple(
            CalendarClaimedResource(
                resource_id=UUID(str(item["resource_id"])),
                display_name=str(item["display_name"]),
                claim_active=item["claim_active"] is True,
            )
            for item in claimed
        ),
    )
