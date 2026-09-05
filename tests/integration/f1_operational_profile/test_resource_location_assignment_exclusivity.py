from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import Connection

PgConnection = Connection[Any]


def _insert_id(conn: PgConnection, statement: str, params: tuple[object, ...]) -> UUID:
    row = conn.execute(statement, params).fetchone()  # type: ignore[arg-type]
    assert row is not None
    return cast(UUID, row[0])


@pytest.mark.integration
@pytest.mark.postgres
def test_resource_location_assignments_reject_cross_location_overlap(
    admin_conn: PgConnection,
) -> None:
    suffix = uuid4().hex
    organization_id = _insert_id(
        admin_conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, 'Assignment Exclusivity Test')
        RETURNING id
        """,
        (f"assignment-exclusivity-{suffix}",),
    )
    first_location_id = _insert_id(
        admin_conn,
        """
        INSERT INTO request_engine.locations (
            organization_id, location_key, display_name, timezone
        ) VALUES (%s, %s, 'First', 'America/Santo_Domingo')
        RETURNING id
        """,
        (organization_id, f"first-{suffix}"),
    )
    second_location_id = _insert_id(
        admin_conn,
        """
        INSERT INTO request_engine.locations (
            organization_id, location_key, display_name, timezone
        ) VALUES (%s, %s, 'Second', 'America/Santo_Domingo')
        RETURNING id
        """,
        (organization_id, f"second-{suffix}"),
    )
    resource_id = _insert_id(
        admin_conn,
        """
        INSERT INTO request_engine.resources (
            organization_id, resource_key, display_name,
            capacity_model, capacity_units
        ) VALUES (%s, %s, 'Exclusive Resource', 'exclusive', 1)
        RETURNING id
        """,
        (organization_id, f"resource-{suffix}"),
    )
    effective_from = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    admin_conn.execute(
        """
        INSERT INTO request_engine.resource_location_assignments (
            organization_id, resource_id, location_id, effective_during
        ) VALUES (%s, %s, %s, tstzrange(%s, NULL, '[)'))
        """,
        (organization_id, resource_id, first_location_id, effective_from),
    )

    try:
        with pytest.raises(psycopg.errors.ExclusionViolation):
            admin_conn.execute(
                """
                INSERT INTO request_engine.resource_location_assignments (
                    organization_id, resource_id, location_id, effective_during
                ) VALUES (%s, %s, %s, tstzrange(%s, NULL, '[)'))
                """,
                (organization_id, resource_id, second_location_id, effective_from),
            )
    finally:
        # psycopg leaves a transactional connection aborted after the expected
        # constraint violation. Release locks so the global PostgreSQL-isolation
        # fixture can truncate authoritatively after this proof.
        admin_conn.rollback()
