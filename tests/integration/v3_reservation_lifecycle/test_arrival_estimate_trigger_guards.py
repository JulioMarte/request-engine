from typing import cast
from uuid import UUID, uuid4

import psycopg
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
)
from ._arrival_estimate_world import create_arrival_world

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.mark.asyncio
async def test_delete_of_active_estimate_is_rejected_as_append_preserving(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    world = create_arrival_world(admin_conn)
    commands = PostgresArrivalEstimateCommands(session_factory)
    estimate = await record_arrival_estimate(
        commands,
        arrival_command(world, eta=arrival_eta(20), revision=1, key=f"eta-{uuid4().hex}"),
    )

    with pytest.raises(psycopg.errors.CheckViolation):
        admin_conn.execute(
            "DELETE FROM request_engine.reservation_arrival_estimates"
            " WHERE organization_id = %s AND id = %s",
            (world.organization_id, estimate.estimate_id),
        )

    assert len(active_rows(admin_conn, world)) == 1


@pytest.mark.asyncio
async def test_superseded_estimate_rows_stay_immutable(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    world = create_arrival_world(admin_conn)
    commands = PostgresArrivalEstimateCommands(session_factory)
    await record_arrival_estimate(
        commands,
        arrival_command(world, eta=arrival_eta(20), revision=1, key=f"eta-{uuid4().hex}"),
    )
    await record_arrival_estimate(
        commands,
        arrival_command(world, eta=arrival_eta(30), revision=2, key=f"eta-{uuid4().hex}"),
    )
    rows = admin_conn.execute(
        "SELECT id, superseded_at FROM request_engine.reservation_arrival_estimates"
        " WHERE organization_id = %s AND reservation_id = %s ORDER BY asserted_at",
        (world.organization_id, world.reservation_id),
    ).fetchall()
    assert len(rows) == 2 and rows[0][1] is not None and rows[1][1] is None
    superseded_id = cast(UUID, rows[0][0])

    with pytest.raises(psycopg.errors.CheckViolation):
        admin_conn.execute(
            "UPDATE request_engine.reservation_arrival_estimates"
            " SET superseded_at = superseded_at + interval '1 minute' WHERE id = %s",
            (superseded_id,),
        )
    with pytest.raises(psycopg.errors.CheckViolation):
        admin_conn.execute(
            "UPDATE request_engine.reservation_arrival_estimates"
            " SET estimated_arrival_at = clock_timestamp() WHERE id = %s",
            (superseded_id,),
        )

    assert [row[2] for row in active_rows(admin_conn, world)] == [True, False]
