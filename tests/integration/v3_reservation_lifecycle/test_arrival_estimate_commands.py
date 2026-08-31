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
)
from ._arrival_estimate_world import create_arrival_world

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.mark.asyncio
async def test_record_creates_one_active_estimate_exposed_by_read_view(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    world = create_arrival_world(admin_conn)
    commands = PostgresArrivalEstimateCommands(session_factory)

    estimate = await record_arrival_estimate(
        commands,
        arrival_command(
            world, eta=arrival_eta(20), source="customer", revision=1, key=f"eta-{uuid4().hex}"
        ),
    )

    assert estimate.source_kind.value == "customer"
    assert estimate.reservation_revision == 2
    assert active_rows(admin_conn, world) == [(estimate.estimated_arrival_at, "customer", False)]
    view = admin_conn.execute(
        """
        SELECT estimated_arrival_at, revision
        FROM request_read.reservation_status_v1
        WHERE organization_id = %s AND reservation_id = %s
        """,
        (world.organization_id, world.reservation_id),
    ).fetchone()
    assert view == (estimate.estimated_arrival_at, 2)


@pytest.mark.asyncio
async def test_second_record_supersedes_previous_estimate_without_rewriting_history(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    world = create_arrival_world(admin_conn)
    commands = PostgresArrivalEstimateCommands(session_factory)
    first = await record_arrival_estimate(
        commands,
        arrival_command(
            world, eta=arrival_eta(20), source="customer", revision=1, key=f"eta-{uuid4().hex}"
        ),
    )

    second = await record_arrival_estimate(
        commands,
        arrival_command(
            world, eta=arrival_eta(35), source="operator", revision=2, key=f"eta-{uuid4().hex}"
        ),
    )

    assert second.estimate_id != first.estimate_id
    assert second.reservation_revision == 3
    rows = active_rows(admin_conn, world)
    assert [row[2] for row in rows] == [True, False]
    assert [row[1] for row in rows] == ["customer", "operator"]
    assert rows[0][0] == first.estimated_arrival_at
