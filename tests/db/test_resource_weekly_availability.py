"""Proofs for optional weekly_availability on booking resource bootstrap.

Creating a Resource with `weekly_availability` must materialize the initial
ResourceLocationAssignment and its recurring availability windows in the same
authoritative transaction, and the windows must drive real slot planning.
"""

from __future__ import annotations

from datetime import UTC, datetime, time
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection

from request_engine.modules.booking.adapters.db.appointment_availability_reader import (
    PostgresAppointmentAvailabilityReader,
)
from request_engine.modules.booking.adapters.db.resource_creation_commands import (
    PostgresResourceCreationCommands,
)
from request_engine.modules.booking.application.commands.create_resource import (
    CreateResourceCommand,
)
from request_engine.modules.booking.application.commands.set_resource_location_availability import (
    ResourceLocationAvailabilityWindow,
)
from request_engine.modules.booking.application.queries.find_appointment_slots import (
    FindAppointmentSlotsQuery,
)
from request_engine.platform.db.session import SessionFactory

pytestmark = pytest.mark.postgres

PgConnection = Connection[Any]

_SUPPLY_SCOPE = "operations.manage_supply"


def _uuid_row(
    conn: PgConnection,
    sql: LiteralString,
    params: tuple[object, ...],
) -> UUID:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


class SupplyWorld:
    organization_id: UUID
    principal_id: UUID
    authority_party_id: UUID
    location_id: UUID
    offering_version_id: UUID
    capability_id: UUID
    requirement_id: UUID


def _seed_supply_world(conn: PgConnection, prefix: str) -> SupplyWorld:
    world = SupplyWorld()
    suffix = uuid4().hex
    world.organization_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (f"{prefix}-{suffix}", f"{prefix} {suffix}"),
    )
    world.principal_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.principals (
            organization_id, principal_kind, external_subject
        ) VALUES (%s, 'agent', %s)
        RETURNING id
        """,
        (world.organization_id, f"operator-{suffix}"),
    )
    world.authority_party_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.parties (
            organization_id, party_kind, display_name
        ) VALUES (%s, 'person', %s)
        RETURNING id
        """,
        (world.organization_id, f"Authority {suffix}"),
    )
    conn.execute(
        """
        INSERT INTO request_engine.representations (
            organization_id, principal_id, represented_party_id,
            authority_kind, scope_key, valid_until
        ) VALUES (%s, %s, %s, 'self', %s, clock_timestamp() + interval '1 day')
        """,
        (
            world.organization_id,
            world.principal_id,
            world.authority_party_id,
            _SUPPLY_SCOPE,
        ),
    )
    world.location_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.locations (
            organization_id, location_key, display_name, timezone, public_data
        ) VALUES (%s, %s, %s, 'America/Santo_Domingo', '{}'::jsonb)
        RETURNING id
        """,
        (world.organization_id, f"location-{suffix}", f"Location {suffix}"),
    )
    conn.execute(
        """
        INSERT INTO request_engine.location_operational_hours (
            organization_id, location_id, weekday, local_start, local_end, active
        ) VALUES (%s, %s, 0, '09:00', '17:00', true)
        """,
        (world.organization_id, world.location_id),
    )
    offering_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.offerings (
            organization_id, offering_key, display_name
        ) VALUES (%s, %s, %s)
        RETURNING id
        """,
        (world.organization_id, f"offering-{suffix}", f"Offering {suffix}"),
    )
    world.offering_version_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.offering_versions (
            organization_id, offering_id, version, duration_minutes,
            bookable, requestable, booking_policy, public_data
        ) VALUES (%s, %s, 1, 30, true, true, %s::jsonb, '{}'::jsonb)
        RETURNING id
        """,
        (world.organization_id, offering_id, '{"slot_step_minutes": 30}'),
    )
    world.capability_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.resource_capabilities (
            organization_id, capability_key, display_name
        ) VALUES (%s, %s, %s)
        RETURNING id
        """,
        (world.organization_id, f"capability-{suffix}", f"Capability {suffix}"),
    )
    world.requirement_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.offering_resource_requirements (
            organization_id, offering_version_id, capability_id, ordinal, quantity
        ) VALUES (%s, %s, %s, 1, 1)
        RETURNING id
        """,
        (world.organization_id, world.offering_version_id, world.capability_id),
    )
    conn.execute(
        """
        INSERT INTO request_engine.offering_version_booking_terms (
            organization_id, offering_version_id, amount, currency
        ) VALUES (%s, %s, 500.00, 'USD')
        """,
        (world.organization_id, world.offering_version_id),
    )
    return world


def _create_command(world: SupplyWorld, *, key: str) -> CreateResourceCommand:
    return CreateResourceCommand(
        organization_id=world.organization_id,
        principal_id=world.principal_id,
        authority_party_id=world.authority_party_id,
        location_id=world.location_id,
        resource_key=f"resource-{key}",
        display_name="Probe resource",
        capacity_model="exclusive",
        capacity_units=1,
        capability_ids=(world.capability_id,),
        weekly_availability=(
            ResourceLocationAvailabilityWindow(
                weekday=0, local_start=time(9, 0), local_end=time(17, 0)
            ),
        ),
        idempotency_key=key,
    )


@pytest.mark.asyncio
async def test_weekly_availability_creates_assignment_and_drives_slot_planning(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    world = _seed_supply_world(admin_conn, "weekly-supply")
    commands = PostgresResourceCreationCommands(command_session_factory)

    state = await commands.create_resource(_create_command(world, key=f"create-{uuid4().hex}"))

    assignment = admin_conn.execute(
        """
        SELECT id, location_id, status, lower(effective_during) IS NOT NULL
        FROM request_engine.resource_location_assignments
        WHERE organization_id = %s AND resource_id = %s
        """,
        (world.organization_id, state.resource_id),
    ).fetchone()
    assert assignment is not None
    assert assignment[1] == world.location_id
    assert assignment[2] == "active"
    assert assignment[3] is True
    assert state.resource_location_assignment_id == assignment[0]

    windows = admin_conn.execute(
        """
        SELECT weekday, local_start::text, local_end::text
        FROM request_engine.resource_location_availability
        WHERE organization_id = %s AND resource_location_assignment_id = %s
        """,
        (world.organization_id, assignment[0]),
    ).fetchall()
    assert windows == [(0, "09:00:00", "17:00:00")]

    # The initial assignment bump must be reflected in the bootstrap response.
    revision = admin_conn.execute(
        """
        SELECT availability_revision
        FROM request_engine.resources
        WHERE organization_id = %s AND id = %s
        """,
        (world.organization_id, state.resource_id),
    ).fetchone()
    assert revision == (state.availability_revision,)
    assert state.availability_revision > 1

    # The persisted windows drive real slot planning at the location.
    slots = await PostgresAppointmentAvailabilityReader(command_session_factory).find_slots(
        FindAppointmentSlotsQuery(
            organization_id=world.organization_id,
            offering_version_id=world.offering_version_id,
            location_id=world.location_id,
            window_start=datetime(2030, 1, 7, 13, 0, tzinfo=UTC),
            window_end=datetime(2030, 1, 7, 16, 0, tzinfo=UTC),
            limit=5,
        )
    )
    assert slots, "resource availability windows must produce bookable slots"
    assert slots[0].start_at == datetime(2030, 1, 7, 13, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_weekly_availability_bootstrap_replays_idempotently(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    world = _seed_supply_world(admin_conn, "weekly-supply-idem")
    key = f"create-{uuid4().hex}"
    commands = PostgresResourceCreationCommands(command_session_factory)

    first = await commands.create_resource(_create_command(world, key=key))
    replay = await commands.create_resource(_create_command(world, key=key))

    assert replay.resource_id == first.resource_id
    assignments = admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.resource_location_assignments
        WHERE organization_id = %s AND resource_id = %s
        """,
        (world.organization_id, first.resource_id),
    ).fetchone()
    assert assignments == (1,)
    windows = admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.resource_location_availability
        WHERE organization_id = %s AND resource_location_assignment_id = %s
        """,
        (world.organization_id, first.resource_location_assignment_id),
    ).fetchone()
    assert windows == (1,)


@pytest.mark.asyncio
async def test_resource_without_weekly_availability_creates_no_assignment(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    world = _seed_supply_world(admin_conn, "weekly-supply-bare")
    suffix = uuid4().hex

    state = await PostgresResourceCreationCommands(command_session_factory).create_resource(
        CreateResourceCommand(
            organization_id=world.organization_id,
            principal_id=world.principal_id,
            authority_party_id=world.authority_party_id,
            location_id=world.location_id,
            resource_key=f"bare-{suffix}",
            display_name="Bare resource",
            capacity_model="exclusive",
            capacity_units=1,
            capability_ids=(),
            idempotency_key=f"create-{suffix}",
        )
    )

    assignments = admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.resource_location_assignments
        WHERE organization_id = %s AND resource_id = %s
        """,
        (world.organization_id, state.resource_id),
    ).fetchone()
    assert assignments == (0,)
    assert state.resource_location_assignment_id is None
