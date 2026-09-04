from typing import Any

import pytest
from psycopg import Connection

PgConnection = Connection[Any]
_TRUSTED_SCHEMAS = {
    "request_admin",
    "request_cmd",
    "request_engine",
    "request_read",
}


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


@pytest.mark.postgres
def test_security_definers_use_closed_trusted_search_paths(
    admin_conn: PgConnection,
) -> None:
    rows = admin_conn.execute(
        """
        SELECT n.nspname, p.proname, p.proconfig
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = ANY(%s)
          AND p.prosecdef
        ORDER BY n.nspname, p.proname, p.oid
        """,
        (sorted(_TRUSTED_SCHEMAS),),
    ).fetchall()

    violations: list[str] = []
    for schema, name, configuration in rows:
        settings = configuration or []
        paths = [item for item in settings if item.startswith("search_path=")]
        if len(paths) != 1:
            violations.append(f"{schema}.{name}: search_path settings={paths!r}")
            continue
        schemas = [item.strip() for item in paths[0].split("=", 1)[1].split(",")]
        trusted_middle = set(schemas[1:-1]).issubset(_TRUSTED_SCHEMAS)
        if schemas[0] != "pg_catalog" or schemas[-1] != "pg_temp" or not trusted_middle:
            violations.append(f"{schema}.{name}: search_path={schemas!r}")

    assert violations == []
