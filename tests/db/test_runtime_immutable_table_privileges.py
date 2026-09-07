from typing import Any, cast

import pytest
from psycopg import Connection

PgConnection = Connection[Any]
_TRUSTED_SCHEMAS = {
    "request_admin",
    "request_cmd",
    "request_engine",
    "request_read",
}
_TRUSTED_DEFINER_OWNERS = {
    "request_engine_discovery_definer",
    "request_engine_schema_owner",
}
_COLUMN_UPDATE_AUTHORITY = {
    "operational_recovery_executions": {
        "communication_task_id",
        "completed_at",
        "failure_code",
        "resulting_reservation_revision",
        "status",
    },
    "queue_entry_recall_holds": {"release_kind", "released_at"},
    "queue_entry_skips": {"consumed_at", "consumed_by_entry_id"},
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
def test_app_update_authority_is_column_scoped(admin_conn: PgConnection) -> None:
    for table, expected_columns in _COLUMN_UPDATE_AUTHORITY.items():
        table_ref = f"request_engine.{table}"
        has_table_update = admin_conn.execute(
            "SELECT has_table_privilege('request_engine_app', %s, 'UPDATE')",
            (table_ref,),
        ).fetchone()
        assert has_table_update == (False,)

        actual_columns = {
            str(row[0])
            for row in admin_conn.execute(
                """
                SELECT a.attname
                FROM pg_attribute a
                WHERE a.attrelid = %s::regclass
                  AND a.attnum > 0
                  AND NOT a.attisdropped
                  AND has_column_privilege(
                      'request_engine_app', a.attrelid, a.attnum, 'UPDATE'
                  )
                ORDER BY a.attname
                """,
                (table_ref,),
            ).fetchall()
        }
        assert actual_columns == expected_columns


@pytest.mark.postgres
def test_security_definers_are_closed_across_all_runtime_schemas(
    admin_conn: PgConnection,
) -> None:
    rows = admin_conn.execute(
        """
        SELECT n.nspname,
               p.proname,
               pg_get_function_identity_arguments(p.oid),
               pg_get_userbyid(p.proowner),
               p.proconfig,
               EXISTS (
                   SELECT 1
                   FROM aclexplode(COALESCE(p.proacl, acldefault('f', p.proowner))) acl
                   WHERE acl.grantee = 0
                     AND acl.privilege_type = 'EXECUTE'
               ) AS public_execute
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = ANY(%s)
          AND p.prosecdef
        ORDER BY n.nspname, p.proname, p.oid
        """,
        (sorted(_TRUSTED_SCHEMAS),),
    ).fetchall()

    violations: list[str] = []
    for (
        schema_value,
        name_value,
        arguments_value,
        owner_value,
        config_value,
        public_value,
    ) in rows:
        schema = str(schema_value)
        name = str(name_value)
        arguments = str(arguments_value)
        owner = str(owner_value)
        configuration = cast(list[str] | None, config_value)
        public_execute = bool(public_value)
        function_name = f"{schema}.{name}({arguments})"

        if owner not in _TRUSTED_DEFINER_OWNERS:
            violations.append(f"{function_name}: owner={owner}")
        if public_execute:
            violations.append(f"{function_name}: PUBLIC EXECUTE")

        settings = configuration or []
        paths = [item for item in settings if item.startswith("search_path=")]
        if len(paths) != 1:
            violations.append(f"{function_name}: search_path settings={paths!r}")
            continue
        schemas = [item.strip() for item in paths[0].split("=", 1)[1].split(",")]
        trusted_middle = set(schemas[1:-1]).issubset(_TRUSTED_SCHEMAS)
        if schemas[0] != "pg_catalog" or schemas[-1] != "pg_temp" or not trusted_middle:
            violations.append(f"{function_name}: search_path={schemas!r}")

    assert violations == []
