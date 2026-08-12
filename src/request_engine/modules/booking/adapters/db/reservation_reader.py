from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping

from request_engine.modules.booking.contracts.appointments import (
    AttendanceStatus,
    Reservation,
    ReservationStatus,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction


class PostgresReservationReader:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def get_reservation(
        self,
        organization_id: UUID,
        reservation_id: UUID,
    ) -> Reservation | None:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            row = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT reservation_id, offering_version_id, subject_party_id,
                                   location_id, lower(during) AS start_at,
                                   upper(during) AS end_at, status, revision,
                                   attendance_status
                            FROM request_read.reservation_status_v1
                            WHERE organization_id = :organization_id
                              AND reservation_id = :reservation_id
                            """
                        ),
                        {
                            "organization_id": organization_id,
                            "reservation_id": reservation_id,
                        },
                    )
                )
                .mappings()
                .first()
            )
        return reservation_from_row(row) if row is not None else None


def reservation_from_row(row: RowMapping) -> Reservation:
    return Reservation(
        id=cast(UUID, row["reservation_id"]),
        offering_version_id=cast(UUID, row["offering_version_id"]),
        subject_party_id=cast(UUID, row["subject_party_id"]),
        location_id=cast(UUID | None, row["location_id"]),
        start_at=cast(datetime, row["start_at"]),
        end_at=cast(datetime, row["end_at"]),
        status=ReservationStatus(cast(str, row["status"])),
        revision=cast(int, row["revision"]),
        attendance_status=AttendanceStatus(cast(str, row["attendance_status"])),
    )
