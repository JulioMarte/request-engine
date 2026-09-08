from typing import Any, cast

import pytest
from psycopg import Connection

PgConnection = Connection[Any]
pytestmark = [pytest.mark.postgres, pytest.mark.invariant, pytest.mark.security]

_RUNTIME = "request_engine_platform_control"
_DEFINER = "request_platform_control_definer"
_FUNCTION = "request_platform.provision_tenant_provisioner(uuid, text, text)"
_EXPECTED_COLUMNS = {
    ("principals", "id", "SELECT"),
    ("principals", "organization_id", "SELECT"),
    ("principals", "principal_plane", "SELECT"),
    ("principals", "principal_kind", "SELECT"),
    ("principals", "active", "SELECT"),
    ("principals", "authority_revision", "SELECT"),
    ("principals", "id", "INSERT"),
    ("principals", "principal_plane", "INSERT"),
    ("principals", "principal_kind", "INSERT"),
    ("principals", "external_subject", "INSERT"),
    ("principals", "authority_revision", "UPDATE"),
    ("principal_authority_grants", "principal_id", "SELECT"),
    ("principal_authority_grants", "principal_plane", "SELECT"),
    ("principal_authority_grants", "authority_plane", "SELECT"),
    ("principal_authority_grants", "capability_key", "SELECT"),
    ("principal_authority_grants", "delegable", "SELECT"),
    ("principal_authority_grants", "status", "SELECT"),
    ("principal_authority_grants", "principal_id", "INSERT"),
    ("principal_authority_grants", "principal_plane", "INSERT"),
    ("principal_authority_grants", "authority_plane", "INSERT"),
    ("principal_authority_grants", "capability_key", "INSERT"),
    ("principal_authority_grants", "delegable", "INSERT"),
    ("principal_authority_grants", "granted_by_principal_id", "INSERT"),
    ("principal_authority_grants", "provenance_kind", "INSERT"),
    ("principal_authority_grants", "provenance_reference", "INSERT"),
}


def test_platform_control_roles_have_exact_elevation(admin_conn: PgConnection) -> None:
    rows = admin_conn.execute(
        """
        SELECT rolname, rolcanlogin, rolsuper, rolbypassrls, rolcreatedb, rolcreaterole
          FROM pg_roles WHERE rolname IN (%s, %s) ORDER BY rolname
        """,
        (_RUNTIME, _DEFINER),
    ).fetchall()
    assert rows == [
        (_RUNTIME, False, False, False, False, False),
        (_DEFINER, False, False, True, False, False),
    ]


def test_platform_control_roles_have_no_memberships(admin_conn: PgConnection) -> None:
    rows = admin_conn.execute(
        """
        SELECT parent.rolname, member.rolname
          FROM pg_auth_members membership
          JOIN pg_roles parent ON parent.oid = membership.roleid
          JOIN pg_roles member ON member.oid = membership.member
         WHERE parent.rolname IN (%s, %s) OR member.rolname IN (%s, %s)
        """,
        (_RUNTIME, _DEFINER, _RUNTIME, _DEFINER),
    ).fetchall()
    assert rows == []


def test_platform_control_definer_has_only_reviewed_columns(
    admin_conn: PgConnection,
) -> None:
    rows = admin_conn.execute(
        """
        SELECT table_name, column_name, privilege_type
          FROM information_schema.column_privileges
         WHERE grantee = %s AND table_schema = 'request_engine'
        """,
        (_DEFINER,),
    ).fetchall()
    actual = {
        (cast(str, table), cast(str, column), cast(str, privilege))
        for table, column, privilege in rows
    }
    assert actual == _EXPECTED_COLUMNS
    assert admin_conn.execute(
        """
        SELECT table_name, privilege_type
          FROM information_schema.role_table_grants
         WHERE grantee = %s AND table_schema = 'request_engine'
        """,
        (_DEFINER,),
    ).fetchall() == []


def test_only_platform_control_runtime_can_execute_command(
    admin_conn: PgConnection,
) -> None:
    assert admin_conn.execute(
        "SELECT has_function_privilege(%s, %s, 'EXECUTE')",
        (_RUNTIME, _FUNCTION),
    ).fetchone() == (True,)
    assert admin_conn.execute(
        "SELECT has_function_privilege('request_engine_app', %s, 'EXECUTE')",
        (_FUNCTION,),
    ).fetchone() == (False,)
    assert admin_conn.execute(
        "SELECT has_function_privilege('public', %s, 'EXECUTE')",
        (_FUNCTION,),
    ).fetchone() == (False,)
