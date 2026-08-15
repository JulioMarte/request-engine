from typing import Any, cast
from uuid import uuid4

import psycopg
import pytest
from psycopg import Connection, sql

PgConnection = Connection[Any]


def _login_conninfo(pg_conninfo: str, role_name: str, password: str) -> str:
    parts = pg_conninfo.split()
    filtered = [
        part for part in parts if not part.startswith("user=") and not part.startswith("password=")
    ]
    return " ".join([*filtered, f"user={role_name}", f"password={password}"])


@pytest.mark.postgres
def test_real_application_login_has_only_the_runtime_table_contract(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    suffix = uuid4().hex[:16]
    role_name = f"request_engine_app_acl_{suffix}"
    password = uuid4().hex
    probe_name = f"runtime_acl_probe_{suffix}"

    admin_conn.execute(
        sql.SQL(
            "CREATE ROLE {} LOGIN INHERIT NOBYPASSRLS NOSUPERUSER "
            "NOCREATEDB NOCREATEROLE PASSWORD {}"
        ).format(sql.Identifier(role_name), sql.Literal(password))
    )
    admin_conn.execute(
        sql.SQL("GRANT request_engine_app TO {} WITH INHERIT TRUE").format(
            sql.Identifier(role_name)
        )
    )

    admin_conn.execute("SET ROLE request_engine_schema_owner")
    try:
        admin_conn.execute(
            sql.SQL("CREATE TABLE request_engine.{} (id uuid PRIMARY KEY)").format(
                sql.Identifier(probe_name)
            )
        )
    finally:
        admin_conn.execute("RESET ROLE")

    app_conn: PgConnection | None = None
    try:
        app_conn = psycopg.connect(
            _login_conninfo(pg_conninfo, role_name, password),
            autocommit=True,
        )

        identity = app_conn.execute(
            """
            SELECT
                current_user,
                session_user,
                pg_has_role(current_user, 'request_engine_app', 'MEMBER'),
                pg_has_role(current_user, 'request_engine_worker', 'MEMBER'),
                pg_has_role(current_user, 'request_engine_admin', 'MEMBER'),
                has_schema_privilege(current_user, 'request_engine', 'USAGE'),
                has_schema_privilege(current_user, 'request_read', 'USAGE'),
                has_schema_privilege(current_user, 'request_admin', 'USAGE')
            """
        ).fetchone()
        assert identity == (
            role_name,
            role_name,
            True,
            False,
            False,
            True,
            True,
            False,
        )

        role_flags = app_conn.execute(
            """
            SELECT rolsuper, rolbypassrls, rolcreatedb, rolcreaterole, rolinherit
            FROM pg_roles
            WHERE rolname = current_user
            """
        ).fetchone()
        assert role_flags == (False, False, False, False, True)

        membership = app_conn.execute(
            """
            SELECT m.inherit_option
            FROM pg_auth_members m
            JOIN pg_roles granted ON granted.oid = m.roleid
            JOIN pg_roles member ON member.oid = m.member
            WHERE granted.rolname = 'request_engine_app'
              AND member.rolname = current_user
            """
        ).fetchone()
        assert membership == (True,)

        idempotency_privileges = app_conn.execute(
            """
            SELECT
                has_table_privilege(
                    current_user,
                    'request_engine.idempotency_records',
                    'SELECT'
                ),
                has_table_privilege(
                    current_user,
                    'request_engine.idempotency_records',
                    'INSERT'
                ),
                has_table_privilege(
                    current_user,
                    'request_engine.idempotency_records',
                    'UPDATE'
                ),
                has_table_privilege(
                    current_user,
                    'request_engine.idempotency_records',
                    'DELETE'
                ),
                has_table_privilege(
                    current_user,
                    'request_engine.idempotency_records',
                    'TRUNCATE'
                )
            """
        ).fetchone()
        assert idempotency_privileges == (True, True, True, False, False)

        missing_contract = app_conn.execute(
            """
            SELECT c.relname
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'request_engine'
              AND c.relkind IN ('r', 'p')
              AND NOT (
                  has_table_privilege(current_user, c.oid, 'SELECT')
                  AND has_table_privilege(current_user, c.oid, 'INSERT')
                  AND has_table_privilege(current_user, c.oid, 'UPDATE')
              )
            ORDER BY c.relname
            """
        ).fetchall()
        assert missing_contract == []

        overprivileged = app_conn.execute(
            """
            SELECT c.relname
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'request_engine'
              AND c.relkind IN ('r', 'p')
              AND (
                  has_table_privilege(current_user, c.oid, 'DELETE')
                  OR has_table_privilege(current_user, c.oid, 'TRUNCATE')
                  OR has_table_privilege(current_user, c.oid, 'REFERENCES')
                  OR has_table_privilege(current_user, c.oid, 'TRIGGER')
              )
            ORDER BY c.relname
            """
        ).fetchall()
        assert overprivileged == []

        probe_privileges = app_conn.execute(
            """
            SELECT
                has_table_privilege(current_user, %s, 'SELECT'),
                has_table_privilege(current_user, %s, 'INSERT'),
                has_table_privilege(current_user, %s, 'UPDATE'),
                has_table_privilege(current_user, %s, 'DELETE')
            """,
            (
                f"request_engine.{probe_name}",
                f"request_engine.{probe_name}",
                f"request_engine.{probe_name}",
                f"request_engine.{probe_name}",
            ),
        ).fetchone()
        assert probe_privileges == (True, True, True, False)

        function_privileges = app_conn.execute(
            """
            SELECT
                has_function_privilege(
                    current_user,
                    'request_cmd.acquire_idempotency(uuid,uuid,text,text,text)',
                    'EXECUTE'
                ),
                has_function_privilege(
                    current_user,
                    'request_cmd.complete_idempotency(uuid,jsonb)',
                    'EXECUTE'
                )
            """
        ).fetchone()
        assert function_privileges == (True, True)

        read_objects_without_select = app_conn.execute(
            """
            SELECT c.relname
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'request_read'
              AND c.relkind IN ('r', 'p', 'v', 'm')
              AND NOT has_table_privilege(current_user, c.oid, 'SELECT')
            ORDER BY c.relname
            """
        ).fetchall()
        assert read_objects_without_select == []
    finally:
        if app_conn is not None:
            app_conn.close()
        admin_conn.execute("SET ROLE request_engine_schema_owner")
        try:
            admin_conn.execute(
                sql.SQL("DROP TABLE IF EXISTS request_engine.{}").format(sql.Identifier(probe_name))
            )
        finally:
            admin_conn.execute("RESET ROLE")
        admin_conn.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role_name)))
        admin_conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role_name)))


@pytest.mark.postgres
def test_application_group_role_has_idempotency_permissions(
    admin_conn: PgConnection,
) -> None:
    row = admin_conn.execute(
        """
        SELECT
            has_table_privilege(
                'request_engine_app',
                'request_engine.idempotency_records',
                'SELECT'
            ),
            has_table_privilege(
                'request_engine_app',
                'request_engine.idempotency_records',
                'INSERT'
            ),
            has_table_privilege(
                'request_engine_app',
                'request_engine.idempotency_records',
                'UPDATE'
            ),
            has_table_privilege(
                'request_engine_app',
                'request_engine.idempotency_records',
                'DELETE'
            )
        """
    ).fetchone()
    assert cast(tuple[bool, bool, bool, bool], row) == (True, True, True, False)


@pytest.mark.postgres
def test_worker_group_role_cannot_delete_authoritative_runtime_rows(
    admin_conn: PgConnection,
) -> None:
    row = admin_conn.execute(
        """
        SELECT
            has_table_privilege(
                'request_engine_worker',
                'request_engine.scheduled_actions',
                'DELETE'
            ),
            has_table_privilege(
                'request_engine_worker',
                'request_engine.outbox_messages',
                'DELETE'
            )
        """
    ).fetchone()
    assert cast(tuple[bool, bool], row) == (False, False)
