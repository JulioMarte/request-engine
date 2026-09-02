from datetime import timedelta
from uuid import uuid4

import pytest

from request_engine.modules.booking.adapters.db.arrival_estimate_commands import (
    PostgresArrivalEstimateCommands,
)
from request_engine.modules.booking.adapters.db.attendance_commands import (
    PostgresAttendanceCommands,
)
from request_engine.modules.booking.adapters.db.day_board_reader import (
    PostgresDayBoardReader,
)
from request_engine.modules.booking.application.commands.check_in_reservation import (
    CheckInReservationCommand,
    check_in_reservation,
)
from request_engine.modules.booking.application.commands.record_arrival_estimate import (
    record_arrival_estimate,
)
from request_engine.modules.booking.application.queries.get_day_board import (
    GetDayBoardQuery,
    get_day_board,
)
from request_engine.platform.db.session import SessionFactory

from ._arrival_estimate_support import PgConnection, arrival_command, reservation_during
from ._arrival_estimate_world import create_arrival_world

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.mark.asyncio
async def test_day_board_composes_eta_and_check_in_without_erasing_assertion(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    world = create_arrival_world(admin_conn)
    start_at, end_at = reservation_during(admin_conn, world)
    eta = start_at + timedelta(minutes=10)
    arrival_commands = PostgresArrivalEstimateCommands(session_factory)

    estimate = await record_arrival_estimate(
        arrival_commands,
        arrival_command(world, eta=eta, revision=1, key=f"board-eta-{uuid4().hex}"),
    )
    reader = PostgresDayBoardReader(session_factory)
    query = GetDayBoardQuery(
        organization_id=world.organization_id,
        window_start=start_at - timedelta(hours=1),
        window_end=end_at + timedelta(hours=1),
    )

    before = await get_day_board(reader, query)

    assert len(before) == 1
    assert before[0].reservation_id == world.reservation_id
    assert before[0].subject_display_name.startswith("Subject ")
    assert before[0].attendance_outcome_status == "pending"
    assert before[0].reported_arrival_estimate_at == estimate.estimated_arrival_at
    assert before[0].effective_arrival_estimate_at == estimate.estimated_arrival_at

    filtered = await get_day_board(
        reader,
        GetDayBoardQuery(
            organization_id=world.organization_id,
            window_start=query.window_start,
            window_end=query.window_end,
            location_id=uuid4(),
        ),
    )
    assert filtered == ()

    await check_in_reservation(
        PostgresAttendanceCommands(session_factory),
        CheckInReservationCommand(
            organization_id=world.organization_id,
            principal_id=world.principal_id,
            reservation_id=world.reservation_id,
            source_key="operator:day-board-proof",
            idempotency_key=f"board-check-in-{uuid4().hex}",
            expected_revision=estimate.reservation_revision,
            allow_subject_override=True,
        ),
    )
    after = await get_day_board(reader, query)

    assert after[0].attendance_outcome_status == "checked_in"
    assert after[0].checked_in_at is not None
    assert after[0].reported_arrival_estimate_at == estimate.estimated_arrival_at
    assert after[0].effective_arrival_estimate_at is None


@pytest.mark.asyncio
async def test_day_board_runtime_read_is_tenant_scoped(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    first = create_arrival_world(admin_conn)
    second = create_arrival_world(admin_conn)
    start_at, end_at = reservation_during(admin_conn, first)
    reader = PostgresDayBoardReader(session_factory)

    rows = await get_day_board(
        reader,
        GetDayBoardQuery(
            organization_id=first.organization_id,
            window_start=start_at - timedelta(hours=1),
            window_end=end_at + timedelta(hours=1),
        ),
    )

    assert [row.reservation_id for row in rows] == [first.reservation_id]
    assert second.reservation_id not in {row.reservation_id for row in rows}
