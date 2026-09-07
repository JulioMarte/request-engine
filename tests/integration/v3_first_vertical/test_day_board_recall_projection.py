from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

import pytest

from request_engine.modules.booking.adapters.db.capacity_error_boundary import (
    CapacitySafeReservationCommands,
)
from request_engine.modules.booking.adapters.db.day_board_reader import (
    PostgresReservationDayBoardReader,
)
from request_engine.modules.booking.application.commands.book_appointment import book_appointment
from request_engine.modules.queue.adapters.db.triage_commands import PostgresQueueTriageCommands
from request_engine.modules.queue.application.commands.triage import RecallHoldCommand
from request_engine.modules.queue.contracts.triage import RecallHoldKind
from request_engine.platform.db.session import SessionFactory

from .booking_boundary_fixture import (
    contextual_booking_command,
    create_booking_boundary_fixture,
)
from .triage_scenario import PgConnection, create_queue


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_day_board_projects_active_queue_recall_gate(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    fixture = create_booking_boundary_fixture(admin_conn)
    start_at = datetime(2026, 9, 7, 14, 0, tzinfo=UTC)
    reservation = await book_appointment(
        CapacitySafeReservationCommands(app_session_factory),
        await contextual_booking_command(
            fixture,
            app_session_factory,
            start_at=start_at,
            key_prefix="day-board-book",
        ),
    )

    queue_id = create_queue(admin_conn, fixture.organization_id)
    entry_row = admin_conn.execute(
        """
        INSERT INTO request_engine.queue_entries (
            organization_id, service_queue_id, subject_party_id,
            reservation_id, arrived_at, admitted_at
        ) VALUES (
            %s, %s, %s, %s,
            '2026-09-07 13:55:00+00', '2026-09-07 13:55:00+00'
        ) RETURNING id
        """,
        (
            fixture.organization_id,
            queue_id,
            fixture.subject_party_id,
            reservation.id,
        ),
    ).fetchone()
    assert entry_row is not None
    queue_entry_id = cast(UUID, entry_row[0])

    held = await PostgresQueueTriageCommands(app_session_factory).recall_hold(
        RecallHoldCommand(
            organization_id=fixture.organization_id,
            principal_id=fixture.principal_id,
            queue_entry_id=queue_entry_id,
            condition_kind=RecallHoldKind.UNTIL_EVENT,
            event_key="external_step_completed",
            expected_revision=1,
            idempotency_key=f"day-board-hold-{uuid4().hex}",
            reason="external prerequisite pending",
        )
    )
    assert held.hold is not None

    rows = await PostgresReservationDayBoardReader(app_session_factory).read_window(
        fixture.organization_id,
        window_start=datetime(2026, 9, 7, 0, 0, tzinfo=UTC),
        window_end=datetime(2026, 9, 8, 0, 0, tzinfo=UTC),
        location_id=fixture.location_id,
    )

    assert len(rows) == 1
    item = rows[0]
    assert item.reservation_id == reservation.id
    assert item.active_queue_entry_count == 1
    assert item.queue_entry_id == queue_entry_id
    assert item.queue_entry_status == "waiting"
    assert item.recall_eligible is False
    assert item.recall_hold_id == held.hold.id
    assert item.recall_hold_kind == RecallHoldKind.UNTIL_EVENT
    assert item.recall_hold_event_key == "external_step_completed"
    assert item.recall_hold_reason == "external prerequisite pending"
    assert item.active_skip_reason is None
