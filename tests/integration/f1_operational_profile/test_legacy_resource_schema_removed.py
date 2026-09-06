from typing import Any

import pytest
from psycopg import Connection

PgConnection = Connection[Any]


@pytest.mark.integration
@pytest.mark.postgres
def test_legacy_resource_location_and_schedule_schema_are_absent(
    admin_conn: PgConnection,
) -> None:
    relation = admin_conn.execute(
        "SELECT to_regclass('request_engine.availability_schedules')"
    ).fetchone()
    assert relation == (None,)

    column = admin_conn.execute(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'request_engine'
          AND table_name = 'resources'
          AND column_name = 'location_id'
        """
    ).fetchone()
    assert column is None


@pytest.mark.integration
@pytest.mark.postgres
def test_no_current_database_routine_references_legacy_availability_schedule(
    admin_conn: PgConnection,
) -> None:
    routines = admin_conn.execute(
        """
        SELECT n.nspname, p.proname
        FROM pg_proc AS p
        JOIN pg_namespace AS n ON n.oid = p.pronamespace
        WHERE n.nspname IN (
            'request_engine', 'request_cmd', 'request_read', 'request_admin'
        )
          AND p.prokind IN ('f', 'p')
          AND pg_get_functiondef(p.oid) ILIKE '%availability_schedules%'
        ORDER BY n.nspname, p.proname
        """
    ).fetchall()
    assert routines == []


@pytest.mark.integration
@pytest.mark.postgres
def test_resource_commitment_guard_does_not_reference_removed_location_column(
    admin_conn: PgConnection,
) -> None:
    definition = admin_conn.execute(
        """
        SELECT pg_get_functiondef(p.oid)
        FROM pg_proc AS p
        JOIN pg_namespace AS n ON n.oid = p.pronamespace
        WHERE n.nspname = 'request_engine'
          AND p.proname = 'guard_resource_commitment_sensitive_change'
          AND p.prokind = 'f'
        """
    ).fetchone()
    assert definition is not None
    sql = definition[0].lower()
    assert 'new.location_id' not in sql
    assert 'old.location_id' not in sql
