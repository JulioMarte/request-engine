from collections.abc import Generator
from contextlib import contextmanager
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from app_function_surface import REVIEWED_APP_EXECUTE_ALLOWLIST
from psycopg import Connection, sql

PgConnection = Connection[Any]
_RUNTIME_SCHEMAS = ("request_engine", "request_read", "request_cmd", "request_admin")


def _login_conninfo(pg_conninfo: str, role_name: str, password: str) -> str:
    parts = [part for part in pg_conninfo.split() if not part.startswith(("user=", "password="))]
    return " ".join([*parts, f"user={role_name}", f"password={password}"])


@contextmanager
def _app_login(admin_conn: PgConnection, pg_conninfo: str) -> Generator[PgConnection]:
    role_name = f"request_engine_app_acl_{uuid4().hex[:16]}"
    password = uuid4().hex
    admin_conn.execute(
        sql.SQL(
            "CREATE ROLE {} LOGIN INHERIT NOBYPASSRLS NOSUPERUSER "
            "NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD {}"
        ).format(sql.Identifier(role_name), sql.Literal(password))
    )
    admin_conn.execute(
        sql.SQL("GRANT request_engine_app TO {} WITH INHERIT TRUE").format(
            sql.Identifier(role_name)
        )
    )

    conn: PgConnection | None = None
    try:
        conn = psycopg.connect(
            _login_conninfo(pg_conninfo, role_name, password),
            autocommit=True,
        )
        yield conn
    finally:
        if conn is not None:
            conn.close()
        admin_conn.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role_name)))
        admin_conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role_name)))


def _executable_application_functions(conn: PgConnection) -> set[str]:
    rows = conn.execute(
        """
        SELECT pg_get_function_identity_arguments(p.oid), n.nspname, p.proname
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = ANY(%s)
          AND has_schema_privilege(current_user, n.oid, 'USAGE')
          AND has_function_privilege(current_user, p.oid, 'EXECUTE')
        """,
        (list(_RUNTIME_SCHEMAS),),
    ).fetchall()
    return {f"{schema}.{name}({arguments})" for arguments, schema, name in rows}


@pytest.mark.postgres
@pytest.mark.security
@pytest.mark.invariant
def test_real_app_login_has_exact_reviewed_function_surface(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    with _app_login(admin_conn, pg_conninfo) as app:
        identity = app.execute(
            """
            SELECT current_user = session_user,
                   pg_has_role(current_user, 'request_engine_app', 'MEMBER'),
                   pg_has_role(current_user, 'request_engine_worker', 'MEMBER'),
                   pg_has_role(current_user, 'request_engine_admin', 'MEMBER'),
                   has_schema_privilege(current_user, 'request_engine', 'USAGE'),
                   has_schema_privilege(current_user, 'request_read', 'USAGE'),
                   has_schema_privilege(current_user, 'request_cmd', 'USAGE'),
                   has_schema_privilege(current_user, 'request_admin', 'USAGE')
            """
        ).fetchone()
        assert identity == (True, True, False, False, True, True, True, False)

        executable = _executable_application_functions(app)
        assert executable == REVIEWED_APP_EXECUTE_ALLOWLIST
        assert not any(signature.startswith("request_admin.") for signature in executable)
