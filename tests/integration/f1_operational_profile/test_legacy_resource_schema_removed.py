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
