from collections.abc import Generator
from contextlib import contextmanager
from typing import Any, cast
from uuid import uuid4

import psycopg
import pytest
from psycopg import Connection, sql

PgConnection = Connection[Any]

_APP_EXECUTE_ALLOWLIST = {
    "request_cmd.acquire_idempotency(p_organization_id uuid, p_principal_id uuid, p_capability text, p_idempotency_key text, p_request_fingerprint text)",
    "request_cmd.cancel_scheduled_action(p_organization_id uuid, p_action_id uuid)",
    "request_cmd.complete_idempotency(p_idempotency_id uuid, p_result_data jsonb)",
    "request_cmd.lock_outbox_message_claim(p_organization_id uuid, p_message_id uuid, p_claim_token uuid)",
    "request_cmd.lock_scheduled_action_claim(p_action_id uuid, p_claim_token uuid)",
    "request_cmd.lock_shared_capacity_roots(p_organization_id uuid, p_resource_ids uuid[])",
    "request_engine.current_authenticated_principal_id()",
    "request_engine.current_correlation_id()",
    "request_engine.current_organization_id()",
    "request_engine.lock_current_party_authority(p_organization_id uuid, p_principal_id uuid, p_represented_party_id uuid, p_scope_key text)",
    "request_engine.resolve_current_party_authority(p_organization_id uuid, p_principal_id uuid, p_represented_party_id uuid, p_scope_key text)",
}


def _login_conninfo(pg_conninfo: str, role_name: str, password: str) -> str:
    parts = pg_conninfo.split()
    filtered = [
        part for part in parts if not part.startswith("user=") and not part.startswith("password=")
    ]
    return " ".join([*filtered, f"user={role_name}", f"password={password}"])


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
        WHERE n.nspname IN ('request_engine', 'request_cmd', 'request_admin')
          AND has_schema_privilege(current_user, n.oid, 'USAGE')
          AND has_function_privilege(current_user, p.oid, 'EXECUTE')
        ORDER BY n.nspname, p.proname, pg_get_function_identity_arguments(p.oid)
        """
    ).fetchall()
    return {
        f"{cast(str, schema_name)}.{cast(str, function_name)}({cast(str, arguments)})"
        for arguments, schema_name, function_name in rows
    }


@pytest.mark.postgres
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
                   has_schema_privilege(current_user, 'request_cmd', 'USAGE'),
                   has_schema_privilege(current_user, 'request_admin', 'USAGE')
            """
        ).fetchone()
        assert identity == (True, True, False, False, True, True, False)

        executable = _executable_application_functions(app)
        assert executable == _APP_EXECUTE_ALLOWLIST
        assert not any(signature.startswith("request_admin.") for signature in executable)
