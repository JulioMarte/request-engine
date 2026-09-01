from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from request_engine.modules.booking.adapters.db.arrival_estimate_commands import (
    PostgresArrivalEstimateCommands,
)
from request_engine.modules.booking.application.commands.record_arrival_estimate import (
    record_arrival_estimate,
)
from request_engine.modules.booking.application.errors import ArrivalEstimateInvalid
from request_engine.platform.db.session import SessionFactory

from ._arrival_estimate_support import (
    PgConnection,
    active_rows,
    arrival_command,
    arrival_eta,
    reservation_during,
)
from ._arrival_estimate_world import ArrivalWorld, create_arrival_world, reservation_revision

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def _eta_after_end(world: ArrivalWorld, conn: PgConnection, minutes: int) -> datetime:
    _, end_at = reservation_during(conn, world)
    return end_at + timedelta(minutes=minutes)


@pytest.mark.asyncio
async def test_past_arrival_is_rejected_as_check_in_fact_not_estimate(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    """An arrival that already happened is a check-in fact, not an estimate; the
    closed rule uses the database clock so app/DB skew cannot approve the past."""

    world = create_arrival_world(admin_conn)
    commands = PostgresArrivalEstimateCommands(session_factory)
    revision = reservation_revision(admin_conn, world)

    with pytest.raises(ArrivalEstimateInvalid) as error:
        await record_arrival_estimate(
            commands,
            arrival_command(
                world,
                eta=datetime.now(UTC) - timedelta(minutes=5),
                revision=revision,
                key=f"eta-{uuid4().hex}",
            ),
        )

    assert "past" in error.value.reason
    assert active_rows(admin_conn, world) == []
    assert reservation_revision(admin_conn, world) == revision


@pytest.mark.asyncio
async def test_arrival_after_reservation_end_is_rejected(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    world = create_arrival_world(admin_conn)
    commands = PostgresArrivalEstimateCommands(session_factory)
    revision = reservation_revision(admin_conn, world)

    with pytest.raises(ArrivalEstimateInvalid) as error:
        await record_arrival_estimate(
            commands,
            arrival_command(
                world,
                eta=_eta_after_end(world, admin_conn, minutes=1),
                revision=revision,
                key=f"eta-{uuid4().hex}",
            ),
        )

    assert "interval end" in error.value.reason
    assert active_rows(admin_conn, world) == []
    assert reservation_revision(admin_conn, world) == revision


@pytest.mark.asyncio
async def test_arrival_before_interval_start_is_accepted(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    """Early arrival is legal: the estimate window has no lower bound against the
    reservation interval start, only against the DB clock and the interval end."""

    world = create_arrival_world(admin_conn)
    commands = PostgresArrivalEstimateCommands(session_factory)
    start_at, _ = reservation_during(admin_conn, world)
    assert start_at > datetime.now(UTC)

    estimate = await record_arrival_estimate(
        commands,
        arrival_command(world, eta=arrival_eta(20), revision=1, key=f"eta-{uuid4().hex}"),
    )

    assert estimate.estimated_arrival_at < start_at
    assert active_rows(admin_conn, world) == [(estimate.estimated_arrival_at, "operator", False)]


@pytest.mark.asyncio
async def test_arrival_exactly_at_interval_end_is_accepted(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    world = create_arrival_world(admin_conn)
    commands = PostgresArrivalEstimateCommands(session_factory)
    _, end_at = reservation_during(admin_conn, world)

    estimate = await record_arrival_estimate(
        commands,
        arrival_command(world, eta=end_at, revision=1, key=f"eta-{uuid4().hex}"),
    )

    assert estimate.estimated_arrival_at == end_at
    assert active_rows(admin_conn, world) == [(end_at, "operator", False)]
