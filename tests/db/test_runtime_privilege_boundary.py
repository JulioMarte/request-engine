from collections.abc import Generator
from contextlib import contextmanager
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from psycopg import Connection, sql
from psycopg.errors import InsufficientPrivilege

PgConnection = Connection[Any]

pytestmark = [pytest.mark.postgres, pytest.mark.invariant, pytest.mark.adversarial]

_APPLICATION_SCHEMAS = ("request_engine", "request_read", "request_cmd", "request_admin")
_RUNTIME_GROUP_ROLES = (
    "request_engine_app",
    "request_engine_worker",
    "request_engine_admin",
    "request_engine_discovery",
)
_FORBIDDEN_ELEVATION_ROLES = {
    "request_engine_schema_owner",
    "request_engine_discovery_definer",
}


def _login_conninfo(pg_conninfo: str, role_name: str, password: str) -> str:
    parts = pg_conninfo.split()
    filtered = [
        part for part in parts if not part.startswith("user=") and not part.startswith("password=")
    ]
    return " ".join([*filtered, f"user={role_name}", f"password={password}"])


@contextmanager
def _runtime_login(
    admin_conn: PgConnection,
    pg_conninfo: str,
    group_role: str,
) -> Generator[PgConnection]:
    role_name = f"{group_role}_boundary_{uuid4().hex[:16]}"
    password = uuid4().hex
    admin_conn.execute(
        sql.SQL(
            "CREATE ROLE {} LOGIN INHERIT NOBYPASSRLS NOSUPERUSER "
            "NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD {}"
        ).format(sql.Identifier(role_name), sql.Literal(password))
    )
    admin_conn.execute(
        sql.SQL("GRANT {} TO {} WITH INHERIT TRUE").format(
            sql.Identifier(group_role), sql.Identifier(role_name)
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


@pytest.mark.postgres
def test_application_functions_are_not_executable_by_public(admin_conn: PgConnection) -> None:
    rows = admin_conn.execute(
        """
        SELECT n.nspname, p.proname, pg_get_function_identity_arguments(p.oid)
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = ANY(%s)
          AND has_function_privilege('public', p.oid, 'EXECUTE')
        ORDER BY n.nspname, p.proname, pg_get_function_identity_arguments(p.oid)
        """,
        (list(_APPLICATION_SCHEMAS),),
    ).fetchall()

    assert rows == []


@pytest.mark.postgres
def test_schema_owner_default_function_acl_denies_public_execute(
    admin_conn: PgConnection,
) -> None:
    rows = admin_conn.execute(
        """
        SELECT COALESCE(n.nspname, ''), acl.privilege_type
        FROM pg_default_acl d
        LEFT JOIN pg_namespace n ON n.oid = d.defaclnamespace
        CROSS JOIN LATERAL aclexplode(d.defaclacl) acl
        WHERE pg_get_userbyid(d.defaclrole) = 'request_engine_schema_owner'
          AND (n.nspname = ANY(%s) OR n.nspname IS NULL)
          AND d.defaclobjtype = 'f'
          AND acl.grantee = 0
          AND acl.privilege_type = 'EXECUTE'
        ORDER BY 1
        """,
        (list(_APPLICATION_SCHEMAS),),
    ).fetchall()

    assert rows == []


@pytest.mark.postgres
def test_schema_owner_default_relation_acl_grants_no_app_authority(
    admin_conn: PgConnection,
) -> None:
    rows = admin_conn.execute(
        """
        SELECT COALESCE(n.nspname, ''), acl.privilege_type
        FROM pg_default_acl d
        LEFT JOIN pg_namespace n ON n.oid = d.defaclnamespace
        CROSS JOIN LATERAL aclexplode(d.defaclacl) acl
        WHERE pg_get_userbyid(d.defaclrole) = 'request_engine_schema_owner'
          AND (n.nspname = ANY(%s) OR n.nspname IS NULL)
          AND d.defaclobjtype = 'r'
          AND acl.grantee = (
              SELECT oid FROM pg_roles WHERE rolname = 'request_engine_app'
          )
        ORDER BY 1, 2
        """,
        (list(_APPLICATION_SCHEMAS),),
    ).fetchall()

    assert rows == []


@pytest.mark.postgres
def test_global_service_classification_authority_is_admin_mediated(
    admin_conn: PgConnection,
) -> None:
    relation_privileges = admin_conn.execute(
        """
        SELECT privilege
        FROM unnest(ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE']) AS privilege
        WHERE has_table_privilege(
            'request_engine_app',
            'request_engine.service_classifications',
            privilege
        )
        ORDER BY privilege
        """
    ).fetchall()
    assert relation_privileges == []

    function_privileges = admin_conn.execute(
        """
        SELECT has_function_privilege(
                   'request_engine_app',
                   'request_engine.lookup_active_service_classification(text)',
                   'EXECUTE'
               ),
               has_function_privilege(
                   'request_engine_app',
                   'request_admin.create_service_classification(text, text, text, text)',
                   'EXECUTE'
               ),
               has_function_privilege(
                   'request_engine_app',
                   'request_admin.retire_service_classification(uuid, bigint, text, text)',
                   'EXECUTE'
               ),
               has_function_privilege(
                   'request_engine_admin',
                   'request_admin.create_service_classification(text, text, text, text)',
                   'EXECUTE'
               ),
               has_function_privilege(
                   'request_engine_admin',
                   'request_admin.retire_service_classification(uuid, bigint, text, text)',
                   'EXECUTE'
               )
        """
    ).fetchone()
    assert function_privileges == (True, False, False, True, True)


@pytest.mark.postgres
def test_recovery_freshness_ledger_is_definer_mediated_for_app(
    admin_conn: PgConnection,
) -> None:
    relation_privileges = admin_conn.execute(
        """
        SELECT privilege
        FROM unnest(ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE']) AS privilege
        WHERE has_table_privilege(
            'request_engine_app',
            'request_engine.recovery_source_revisions',
            privilege
        )
        ORDER BY privilege
        """
    ).fetchall()
    assert relation_privileges == []

    function_privileges = admin_conn.execute(
        """
        SELECT has_function_privilege(
                   'request_engine_app',
                   'request_read.recovery_source_revision(uuid, uuid)',
                   'EXECUTE'
               ),
               has_function_privilege(
                   'request_engine_app',
                   'request_cmd.lock_recovery_source_revision(uuid, uuid)',
                   'EXECUTE'
               ),
               has_function_privilege(
                   'request_engine_app',
                   'request_engine.bump_recovery_source_revision(uuid, uuid)',
                   'EXECUTE'
               )
        """
    ).fetchone()
    assert function_privileges == (True, True, False)


@pytest.mark.parametrize("group_role", _RUNTIME_GROUP_ROLES)
def test_real_runtime_logins_cannot_escalate_or_create_application_objects(
    admin_conn: PgConnection,
    pg_conninfo: str,
    group_role: str,
) -> None:
    with _runtime_login(admin_conn, pg_conninfo, group_role) as runtime:
        identity = runtime.execute(
            """
            SELECT current_user = session_user,
                   rolsuper, rolbypassrls, rolcreatedb, rolcreaterole
            FROM pg_roles
            WHERE rolname = current_user
            """
        ).fetchone()
        assert identity == (True, False, False, False, False)

        runtime.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(group_role)))
        current = runtime.execute(
            "SELECT current_user, rolbypassrls FROM pg_roles WHERE rolname = current_user"
        ).fetchone()
        assert current == (group_role, group_role == "request_engine_admin")

        probe = f"runtime_boundary_{uuid4().hex[:16]}"
        with pytest.raises(InsufficientPrivilege):
            runtime.execute(
                sql.SQL("CREATE TABLE request_engine.{} (id integer)").format(sql.Identifier(probe))
            )
        runtime.execute("RESET ROLE")

        forbidden = (set(_RUNTIME_GROUP_ROLES) - {group_role}) | _FORBIDDEN_ELEVATION_ROLES
        for forbidden_role in sorted(forbidden):
            with pytest.raises(InsufficientPrivilege):
                runtime.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(forbidden_role)))
