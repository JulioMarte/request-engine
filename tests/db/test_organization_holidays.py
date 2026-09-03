"""Proofs for organization-wide holiday declaration (operations surface).

Declaring an organization holiday must materialize full-day `unavailable`
location_hours_exceptions for every ACTIVE Location in its own timezone,
inside one authoritative transaction, idempotently — and never touch
inactive Locations.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from psycopg import Connection

from request_engine.modules.catalog.adapters.db.organization_holiday_commands import (
    PostgresOrganizationHolidayCommands,
)
from request_engine.modules.catalog.application.commands.declare_organization_holidays import (
    DeclareOrganizationHolidaysCommand,
    OrganizationHolidayInput,
)
from request_engine.platform.db.session import SessionFactory

pytestmark = pytest.mark.postgres

PgConnection = Connection[Any]

_PROFILE_SCOPE = "operations.manage_profile"


def _uuid_row(
    conn: PgConnection,
    sql: LiteralString,
    params: tuple[object, ...],
) -> UUID:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


class HolidayWorld:
    organization_id: UUID
    principal_id: UUID
    authority_party_id: UUID
    active_location_ids: tuple[UUID, ...]
    inactive_location_id: UUID


def _seed_holiday_world(conn: PgConnection, prefix: str) -> HolidayWorld:
    world = HolidayWorld()
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
            _PROFILE_SCOPE,
        ),
    )
    timezones = ("America/Santo_Domingo", "Europe/Madrid")
    active: list[UUID] = []
    for index, timezone in enumerate(timezones):
        location_id = _uuid_row(
            conn,
            """
            INSERT INTO request_engine.locations (
                organization_id, location_key, display_name, timezone, active, public_data
            ) VALUES (%s, %s, %s, %s, true, '{}'::jsonb)
            RETURNING id
            """,
            (
                world.organization_id,
                f"location-{suffix}-{index}",
                f"Location {index}",
                timezone,
            ),
        )
        active.append(location_id)
    world.active_location_ids = tuple(active)
    world.inactive_location_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.locations (
            organization_id, location_key, display_name, timezone, active, public_data
        ) VALUES (%s, %s, %s, 'America/Santo_Domingo', false, '{}'::jsonb)
        RETURNING id
        """,
        (
            world.organization_id,
            f"location-{suffix}-inactive",
            "Inactive location",
        ),
    )
    return world


def _holiday_command(
    world: HolidayWorld,
    *,
    key: str,
    holidays: tuple[OrganizationHolidayInput, ...] | None = None,
) -> DeclareOrganizationHolidaysCommand:
    return DeclareOrganizationHolidaysCommand(
        organization_id=world.organization_id,
        principal_id=world.principal_id,
        authority_party_id=world.authority_party_id,
        holidays=holidays
        or (OrganizationHolidayInput(date=date(2030, 12, 25), reason="Christmas"),),
        idempotency_key=key,
    )


def _expected_day_range(
    location_id: UUID,
    world: HolidayWorld,
    holiday_date: str,
) -> tuple[datetime, datetime]:
    """Independent oracle: full local day, computed with zoneinfo directly."""

    timezones = dict(
        zip(world.active_location_ids, ("America/Santo_Domingo", "Europe/Madrid"), strict=True)
    )
    timezone = ZoneInfo(timezones[location_id])
    day = datetime.strptime(holiday_date, "%Y-%m-%d").date()
    start = datetime.combine(day, datetime.min.time(), tzinfo=timezone).astimezone(UTC)
    end = start + timedelta(days=1)
    return start, end


def _exceptions(
    conn: PgConnection,
    world: HolidayWorld,
    location_id: UUID,
) -> list[tuple[datetime, datetime, str, str | None]]:
    rows = conn.execute(
        """
        SELECT lower(during), upper(during), exception_kind, reason
        FROM request_engine.location_hours_exceptions
        WHERE organization_id = %s AND location_id = %s AND active
        ORDER BY lower(during)
        """,
        (world.organization_id, location_id),
    ).fetchall()
    return [(row[0], row[1], row[2], row[3]) for row in rows]


@pytest.mark.asyncio
async def test_holiday_materializes_full_day_exceptions_for_active_locations(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    world = _seed_holiday_world(admin_conn, "org-holidays")
    holiday_date = "2030-12-25"

    state = await PostgresOrganizationHolidayCommands(
        command_session_factory
    ).declare_organization_holidays(_holiday_command(world, key=f"holidays-{uuid4().hex}"))

    assert state.locations_covered == 2
    assert state.exceptions_created == 2
    assert state.exceptions_already_declared == 0

    for location_id in world.active_location_ids:
        start, end = _expected_day_range(location_id, world, holiday_date)
        assert _exceptions(admin_conn, world, location_id) == [
            (start, end, "unavailable", "Christmas")
        ]

    inactive = _exceptions(admin_conn, world, world.inactive_location_id)
    assert inactive == []


@pytest.mark.asyncio
async def test_holiday_declaration_is_idempotent_across_keys_and_replays(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    world = _seed_holiday_world(admin_conn, "org-holidays-idem")
    commands = PostgresOrganizationHolidayCommands(command_session_factory)
    key = f"holidays-{uuid4().hex}"

    first = await commands.declare_organization_holidays(_holiday_command(world, key=key))
    replay = await commands.declare_organization_holidays(_holiday_command(world, key=key))
    repeat_new_key = await commands.declare_organization_holidays(
        _holiday_command(world, key=f"holidays-{uuid4().hex}")
    )

    assert replay == first
    assert repeat_new_key.exceptions_created == 0
    assert repeat_new_key.exceptions_already_declared == 2

    total = admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.location_hours_exceptions
        WHERE organization_id = %s
        """,
        (world.organization_id,),
    ).fetchone()
    assert total == (2,)


@pytest.mark.asyncio
async def test_holiday_declaration_leaves_inactive_locations_untouched(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    world = _seed_holiday_world(admin_conn, "org-holidays-inactive")

    before = admin_conn.execute(
        """
        SELECT operational_revision
        FROM request_engine.locations
        WHERE organization_id = %s AND id = %s
        """,
        (world.organization_id, world.inactive_location_id),
    ).fetchone()

    await PostgresOrganizationHolidayCommands(
        command_session_factory
    ).declare_organization_holidays(_holiday_command(world, key=f"holidays-{uuid4().hex}"))

    after = admin_conn.execute(
        """
        SELECT operational_revision
        FROM request_engine.locations
        WHERE organization_id = %s AND id = %s
        """,
        (world.organization_id, world.inactive_location_id),
    ).fetchone()
    assert before == after
    assert _exceptions(admin_conn, world, world.inactive_location_id) == []
