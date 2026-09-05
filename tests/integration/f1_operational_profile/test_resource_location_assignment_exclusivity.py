from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import Connection

PgConnection = Connection[Any]


def _uuid(
    conn: PgConnection,
    sql: LiteralString,
    params: tuple[object, ...],
) -> UUID:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


@pytest.mark.integration
@pytest.mark.postgres
def test_resource_assignment_rejects_cross_location_overlap(admin_conn: PgConnection) -> None:
    suffix = uuid4().hex
    organization_id = _uuid(
        admin_conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (f"assignment-exclusivity-{suffix}", "Assignment Exclusivity"),
    )
    location_one = _uuid(
        admin_conn,
        """
        INSERT INTO request_engine.locations (
            organization_id, location_key, display_name, timezone
        ) VALUES (%s, %s, %s, 'America/Santo_Domingo')
        RETURNING id
        """,
        (organization_id, f"location-one-{suffix}", "Location One"),
    )
    location_two = _uuid(
        admin_conn,
        """
        INSERT INTO request_engine.locations (
            organization_id, location_key, display_name, timezone
        ) VALUES (%s, %s, %s, 'America/Santo_Domingo')
        RETURNING id
        """,
        (organization_id, f"location-two-{suffix}", "Location Two"),
    )
    resource_id = _uuid(
        admin_conn,
        """
        INSERT INTO request_engine.resources (
            organization_id, resource_key, display_name,
            capacity_model, capacity_units
        ) VALUES (%s, %s, %s, 'exclusive', 1)
        RETURNING id
        """,
        (organization_id, f"resource-{suffix}", "Exclusive Resource"),
    )
    admin_conn.execute(
        """
        INSERT INTO request_engine.resource_location_assignments (
            organization_id, resource_id, location_id, effective_during
        ) VALUES (
            %s, %s, %s,
            tstzrange('2030-01-01T00:00:00+00', '2030-02-01T00:00:00+00', '[)')
        )
        """,
        (organization_id, resource_id, location_one),
    )

    with pytest.raises(psycopg.errors.ExclusionViolation):
        admin_conn.execute(
            """
            INSERT INTO request_engine.resource_location_assignments (
                organization_id, resource_id, location_id, effective_during
            ) VALUES (
                %s, %s, %s,
                tstzrange('2030-01-15T00:00:00+00', '2030-03-01T00:00:00+00', '[)')
            )
            """,
            (organization_id, resource_id, location_two),
        )
    admin_conn.rollback()
