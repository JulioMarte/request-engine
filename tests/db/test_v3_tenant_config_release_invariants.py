from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import Connection, Error

PgConnection = Connection[Any]


def _uuid_row(
    conn: PgConnection,
    sql: LiteralString,
    params: tuple[object, ...] = (),
) -> UUID:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _organization(conn: PgConnection, label: str) -> UUID:
    suffix = uuid4().hex
    return _uuid_row(
        conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (f"config-{label}-{suffix}", f"Config {label} {suffix}"),
    )


def _location(conn: PgConnection, organization_id: UUID, label: str) -> UUID:
    return _uuid_row(
        conn,
        """
        INSERT INTO request_engine.locations (
            organization_id, location_key, display_name, timezone
        ) VALUES (%s, %s, %s, 'UTC')
        RETURNING id
        """,
        (organization_id, f"loc-{uuid4().hex}", label),
    )


def _capability(conn: PgConnection, organization_id: UUID, label: str) -> UUID:
    return _uuid_row(
        conn,
        """
        INSERT INTO request_engine.resource_capabilities (
            organization_id, capability_key, display_name
        ) VALUES (%s, %s, %s)
        RETURNING id
        """,
        (organization_id, f"cap-{uuid4().hex}", label),
    )


def _resource(
    conn: PgConnection,
    organization_id: UUID,
    location_id: UUID,
    label: str,
) -> UUID:
    return _uuid_row(
        conn,
        """
        INSERT INTO request_engine.resources (
            organization_id, location_id, resource_key, display_name,
            capacity_model, capacity_units
        ) VALUES (%s, %s, %s, %s, 'exclusive', 1)
        RETURNING id
        """,
        (organization_id, location_id, f"resource-{uuid4().hex}", label),
    )


@pytest.mark.postgres
def test_i08_resource_capability_location_configuration_cannot_cross_tenant(
    admin_conn: PgConnection,
) -> None:
    org_a = _organization(admin_conn, "a")
    org_b = _organization(admin_conn, "b")
    location_a = _location(admin_conn, org_a, "Location A")
    location_b = _location(admin_conn, org_b, "Location B")
    capability_a = _capability(admin_conn, org_a, "Capability A")
    capability_b = _capability(admin_conn, org_b, "Capability B")
    resource_a = _resource(admin_conn, org_a, location_a, "Resource A")

    with pytest.raises(Error) as foreign_location:
        admin_conn.execute(
            """
            INSERT INTO request_engine.resources (
                organization_id, location_id, resource_key, display_name,
                capacity_model, capacity_units
            ) VALUES (%s, %s, %s, 'Cross location', 'exclusive', 1)
            """,
            (org_a, location_b, f"cross-location-{uuid4().hex}"),
        )
    assert foreign_location.value.sqlstate == "23503"

    with pytest.raises(Error) as foreign_capability:
        admin_conn.execute(
            """
            INSERT INTO request_engine.resource_capability_assignments (
                organization_id, resource_id, capability_id
            ) VALUES (%s, %s, %s)
            """,
            (org_a, resource_a, capability_b),
        )
    assert foreign_capability.value.sqlstate == "23503"

    with pytest.raises(Error) as foreign_schedule:
        admin_conn.execute(
            """
            INSERT INTO request_engine.availability_schedules (
                organization_id, resource_id, weekday, local_start, local_end, timezone
            ) VALUES (%s, %s, 1, '09:00', '10:00', 'UTC')
            """,
            (org_b, resource_a),
        )
    assert foreign_schedule.value.sqlstate == "23503"

    admin_conn.execute(
        """
        INSERT INTO request_engine.resource_capability_assignments (
            organization_id, resource_id, capability_id
        ) VALUES (%s, %s, %s)
        """,
        (org_a, resource_a, capability_a),
    )


@pytest.mark.postgres
def test_i09_schedule_mutation_serializes_through_resource_and_advances_revision(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    organization_id = _organization(admin_conn, "schedule")
    location_id = _location(admin_conn, organization_id, "Schedule location")
    resource_id = _resource(admin_conn, organization_id, location_id, "Schedule resource")
    initial_row = admin_conn.execute(
        """
        SELECT availability_revision
        FROM request_engine.resources
        WHERE organization_id = %s AND id = %s
        """,
        (organization_id, resource_id),
    ).fetchone()
    assert initial_row is not None
    initial_revision = cast(int, initial_row[0])

    locker: PgConnection = psycopg.connect(pg_conninfo, autocommit=False)
    writer: PgConnection = psycopg.connect(pg_conninfo, autocommit=False)
    try:
        locker.execute(
            """
            SELECT id
            FROM request_engine.resources
            WHERE organization_id = %s AND id = %s
            FOR UPDATE
            """,
            (organization_id, resource_id),
        ).fetchone()

        writer.execute("SET LOCAL lock_timeout = '250ms'")
        with pytest.raises(Error) as blocked:
            writer.execute(
                """
                INSERT INTO request_engine.availability_schedules (
                    organization_id, resource_id, weekday, local_start, local_end, timezone
                ) VALUES (%s, %s, 1, '09:00', '10:00', 'UTC')
                """,
                (organization_id, resource_id),
            )
        assert blocked.value.sqlstate == "55P03"
        writer.rollback()

        locker.commit()
        writer.execute(
            """
            INSERT INTO request_engine.availability_schedules (
                organization_id, resource_id, weekday, local_start, local_end, timezone
            ) VALUES (%s, %s, 1, '09:00', '10:00', 'UTC')
            """,
            (organization_id, resource_id),
        )
        writer.commit()

        after_schedule = admin_conn.execute(
            """
            SELECT availability_revision
            FROM request_engine.resources
            WHERE organization_id = %s AND id = %s
            """,
            (organization_id, resource_id),
        ).fetchone()
        assert after_schedule == (initial_revision + 1,)

        admin_conn.execute(
            """
            INSERT INTO request_engine.schedule_exceptions (
                organization_id, resource_id, during, exception_kind, reason
            ) VALUES (
                %s, %s,
                tstzrange('2099-01-01 09:00+00', '2099-01-01 10:00+00', '[)'),
                'unavailable', 'I09 revision proof'
            )
            """,
            (organization_id, resource_id),
        )
        assert admin_conn.execute(
            """
            SELECT availability_revision
            FROM request_engine.resources
            WHERE organization_id = %s AND id = %s
            """,
            (organization_id, resource_id),
        ).fetchone() == (initial_revision + 2,)
    finally:
        locker.rollback()
        writer.rollback()
        locker.close()
        writer.close()
