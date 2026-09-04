from typing import Any

import pytest
from psycopg import Connection

PgConnection = Connection[Any]


@pytest.mark.postgres
def test_app_has_no_update_privilege_on_immutable_tables(
    admin_conn: PgConnection,
) -> None:
    rows = admin_conn.execute(
        """
        SELECT c.relname
        FROM pg_trigger t
        JOIN pg_class c ON c.oid = t.tgrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        JOIN pg_proc p ON p.oid = t.tgfoid
        JOIN pg_namespace pn ON pn.oid = p.pronamespace
        WHERE NOT t.tgisinternal
          AND n.nspname = 'request_engine'
          AND pn.nspname = 'request_engine'
          AND p.proname = 'reject_immutable_mutation'
          AND has_table_privilege('request_engine_app', c.oid, 'UPDATE')
        ORDER BY c.relname
        """
    ).fetchall()

    assert rows == []
