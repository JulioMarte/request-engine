from dataclasses import fields
from uuid import uuid4

import pytest

from request_engine.modules.booking.adapters.db.arrival_estimate_commands import (
    PostgresArrivalEstimateCommands,
)
from request_engine.modules.booking.application.commands.record_arrival_estimate import (
    RecordArrivalEstimateCommand,
    record_arrival_estimate,
)
from request_engine.platform.db.session import SessionFactory

from ._arrival_estimate_support import (
    PgConnection,
    active_rows,
    arrival_command,
    arrival_eta,
)
from ._arrival_estimate_world import ArrivalWorld, create_arrival_world
from ._authority_race_support import create_representation

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def _world_with_representation(admin_conn: PgConnection) -> ArrivalWorld:
    world = create_arrival_world(admin_conn)
    create_representation(
        admin_conn,
        organization_id=world.organization_id,
        principal_id=world.principal_id,
        party_id=world.subject_party_id,
    )
    return world


@pytest.mark.asyncio
async def test_record_creates_one_active_estimate_exposed_by_read_view(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    world = _world_with_representation(admin_conn)
    commands = PostgresArrivalEstimateCommands(session_factory)

    estimate = await record_arrival_estimate(
        commands,
        arrival_command(world, eta=arrival_eta(20), revision=1, key=f"eta-{uuid4().hex}"),
    )

    assert estimate.source_kind.value == "operator"
    assert estimate.reservation_revision == 2
    assert active_rows(admin_conn, world) == [(estimate.estimated_arrival_at, "operator", False)]
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
async def test_subject_authority_derives_customer_source_and_legacy_input_is_gone(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    """Provenance is derived from the resolved authority mode. A subject-authorized
    recording must store source_kind='customer' even though the legacy API body sent
    source_kind='operator'; the command input no longer exists to carry it."""

    world = _world_with_representation(admin_conn)
    commands = PostgresArrivalEstimateCommands(session_factory)

    command_fields = {field.name for field in fields(RecordArrivalEstimateCommand)}
    assert "source_kind" not in command_fields

    estimate = await record_arrival_estimate(
        commands,
        arrival_command(
            world, eta=arrival_eta(20), revision=1, key=f"eta-{uuid4().hex}", override=False
        ),
    )

    assert estimate.source_kind.value == "customer"
    assert active_rows(admin_conn, world) == [(estimate.estimated_arrival_at, "customer", False)]


@pytest.mark.asyncio
async def test_operator_override_derives_operator_source(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    world = create_arrival_world(admin_conn)
    commands = PostgresArrivalEstimateCommands(session_factory)

    estimate = await record_arrival_estimate(
        commands,
        arrival_command(world, eta=arrival_eta(20), revision=1, key=f"eta-{uuid4().hex}"),
    )

    assert estimate.source_kind.value == "operator"
    assert active_rows(admin_conn, world) == [(estimate.estimated_arrival_at, "operator", False)]


@pytest.mark.asyncio
async def test_second_record_supersedes_previous_estimate_without_rewriting_history(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    world = _world_with_representation(admin_conn)
    commands = PostgresArrivalEstimateCommands(session_factory)
    first = await record_arrival_estimate(
        commands,
        arrival_command(
            world, eta=arrival_eta(20), revision=1, key=f"eta-{uuid4().hex}", override=False
        ),
    )

    second = await record_arrival_estimate(
        commands,
        arrival_command(world, eta=arrival_eta(35), revision=2, key=f"eta-{uuid4().hex}"),
    )

    assert second.estimate_id != first.estimate_id
    assert second.reservation_revision == 3
    rows = active_rows(admin_conn, world)
    assert [row[2] for row in rows] == [True, False]
    assert [row[1] for row in rows] == ["customer", "operator"]
    assert rows[0][0] == first.estimated_arrival_at
