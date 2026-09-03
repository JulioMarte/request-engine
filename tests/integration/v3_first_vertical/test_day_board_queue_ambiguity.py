from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import pytest

from request_engine.modules.booking.adapters.db.day_board_reader import (
    PostgresReservationDayBoardReader,
)
from request_engine.platform.db.session import SessionFactory

from .booking_boundary_fixture import create_booking_boundary_fixture
from .triage_scenario import PgConnection, create_queue


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_day_board_does_not_pick_one_of_multiple_active_queue_entries(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    fixture = create_booking_boundary_fixture(admin_conn)
    row = admin_conn.execute(
        """
        INSERT INTO request_engine.reservations (
            organization_id, offering_version_id, subject_party_id,
            location_id, during, booking_policy_snapshot
        ) VALUES (
            %s, %s, %s, %s,
            tstzrange('2026-09-03 14:00:00+00', '2026-09-03 14:30:00+00', '[)'),
            '{}'::jsonb
        ) RETURNING id
        """,
        (
            fixture.organization_id,
            fixture.offering_version_id,
            fixture.subject_party_id,
            fixture.location_id,
        ),
    ).fetchone()
    assert row is not None
    reservation_id = cast(UUID, row[0])

    for minute in (50, 55):
        queue_id = create_queue(admin_conn, fixture.organization_id)
        admin_conn.execute(
            """
            INSERT INTO request_engine.queue_entries (
                organization_id, service_queue_id, subject_party_id,
                reservation_id, arrived_at, admitted_at
            ) VALUES (%s, %s, %s, %s, %s::timestamptz, %s::timestamptz)
            """,
            (
                fixture.organization_id,
                queue_id,
                fixture.subject_party_id,
                reservation_id,
                f"2026-09-03 13:{minute}:00+00",
                f"2026-09-03 13:{minute}:00+00",
            ),
        )

    rows = await PostgresReservationDayBoardReader(app_session_factory).read_window(
        fixture.organization_id,
        window_start=datetime(2026, 9, 3, 0, 0, tzinfo=UTC),
        window_end=datetime(2026, 9, 4, 0, 0, tzinfo=UTC),
        location_id=fixture.location_id,
    )

    assert len(rows) == 1
    item = rows[0]
    assert item.active_queue_entry_count == 2
    assert item.queue_entry_id is None
    assert item.queue_entry_status is None
    assert item.recall_eligible is None
    assert item.recall_hold_id is None
    assert item.active_skip_reason is None
