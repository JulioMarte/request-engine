import asyncio
from uuid import uuid4

import pytest

from request_engine.modules.booking.adapters.db.arrival_estimate_commands import (
    PostgresArrivalEstimateCommands,
)
from request_engine.modules.booking.application.commands.record_arrival_estimate import (
    record_arrival_estimate,
)
from request_engine.platform.db.session import SessionFactory

from ._arrival_estimate_support import (
    PgConnection,
    active_rows,
    arrival_command,
    arrival_eta,
    wait_until_lock_blocked,
)
from ._arrival_estimate_world import create_arrival_world, reservation_revision
from ._authority_race_support import connect, lock_audit_barrier, wait_until_audit_blocked

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.concurrency]


@pytest.mark.asyncio
async def test_concurrent_estimate_commands_serialize_on_reservation_lock(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    """Two simultaneous record_arrival_estimate commands for one reservation serialize
    on the reservation row lock: both commit, history stays append-only, and exactly
    one active estimate survives with the loser's row superseded."""

    world = create_arrival_world(admin_conn)
    commands = PostgresArrivalEstimateCommands(session_factory)
    revision = reservation_revision(admin_conn, world)
    blocker = connect()
    try:
        lock_audit_barrier(blocker)
        first_task = asyncio.create_task(
            record_arrival_estimate(
                commands,
                arrival_command(
                    world,
                    eta=arrival_eta(15),
                    revision=revision,
                    key=f"eta-{uuid4().hex}",
                ),
            )
        )
        await wait_until_audit_blocked(admin_conn)
        second_task = asyncio.create_task(
            record_arrival_estimate(
                commands,
                arrival_command(
                    world,
                    eta=arrival_eta(40),
                    revision=revision + 1,
                    key=f"eta-{uuid4().hex}",
                ),
            )
        )
        await wait_until_lock_blocked(
            admin_conn,
            "%FROM request_engine.reservations%FOR UPDATE%",
            "second estimate command never blocked on the reservation lock",
        )
        blocker.commit()
        first = await asyncio.wait_for(first_task, timeout=5)
        second = await asyncio.wait_for(second_task, timeout=5)
    finally:
        if not blocker.closed:
            blocker.rollback()
        blocker.close()

    assert first.estimate_id != second.estimate_id
    assert first.reservation_revision == revision + 1
    assert second.reservation_revision == revision + 2
    rows = active_rows(admin_conn, world)
    assert [(row[1], row[2]) for row in rows] == [("operator", True), ("operator", False)]
    assert rows[0][0] == first.estimated_arrival_at
    assert rows[1][0] == second.estimated_arrival_at
    assert reservation_revision(admin_conn, world) == revision + 2
