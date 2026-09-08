from typing import Any, cast

import pytest
from psycopg import Connection

PgConnection = Connection[Any]
pytestmark = [pytest.mark.postgres, pytest.mark.invariant, pytest.mark.security]

_ROLE = "request_bootstrap_definer"
_EXPECTED_COLUMNS = {
    ("identity_authorities", "id", "SELECT"),
    ("identity_authorities", "kind", "SELECT"),
    ("identity_authorities", "status", "SELECT"),
    ("platform_bootstrap_intents", "id", "SELECT"),
    ("platform_bootstrap_intents", "token_digest", "SELECT"),
    ("platform_bootstrap_intents", "permitted_action", "SELECT"),
    ("platform_bootstrap_intents", "provenance_reference", "SELECT"),
    ("platform_bootstrap_intents", "status", "SELECT"),
    ("platform_bootstrap_intents", "expires_at", "SELECT"),
    ("platform_bootstrap_intents", "status", "UPDATE"),
    ("platform_bootstrap_intents", "revision", "UPDATE"),
    ("platform_bootstrap_intents", "consumed_at", "UPDATE"),
    ("native_identities", "id", "INSERT"),
    ("native_identities", "identity_authority_id", "INSERT"),
    ("native_identities", "login_handle", "INSERT"),
    ("native_credentials", "id", "INSERT"),
    ("native_credentials", "native_identity_id", "INSERT"),
    ("native_credentials", "verifier", "INSERT"),
    ("principals", "id", "SELECT"),
    ("principals", "organization_id", "SELECT"),
    ("principals", "principal_plane", "SELECT"),
    ("principals", "active", "SELECT"),
    ("principals", "id", "INSERT"),
    ("principals", "principal_plane", "INSERT"),
    ("principals", "principal_kind", "INSERT"),
    ("principals", "external_subject", "INSERT"),
    ("principals", "authority_revision", "UPDATE"),
    ("identity_bindings", "id", "INSERT"),
    ("identity_bindings", "principal_id", "INSERT"),
    ("identity_bindings", "principal_plane", "INSERT"),
    ("identity_bindings", "identity_authority_id", "INSERT"),
    ("identity_bindings", "subject_id", "INSERT"),
    ("identity_bindings", "status", "INSERT"),
    ("principal_authority_grants", "principal_id", "INSERT"),
    ("principal_authority_grants", "principal_plane", "INSERT"),
    ("principal_authority_grants", "authority_plane", "INSERT"),
    ("principal_authority_grants", "capability_key", "INSERT"),
    ("principal_authority_grants", "delegable", "INSERT"),
    ("principal_authority_grants", "provenance_kind", "INSERT"),
    ("principal_authority_grants", "provenance_reference", "INSERT"),
}


def test_bootstrap_definer_has_exact_role_elevation(admin_conn: PgConnection) -> None:
    row = admin_conn.execute(
        """
        SELECT rolcanlogin, rolsuper, rolbypassrls, rolcreatedb, rolcreaterole,
               rolreplication, rolconnlimit
          FROM pg_roles WHERE rolname = %s
        """,
        (_ROLE,),
    ).fetchone()
    assert row == (False, False, True, False, False, False, -1)


def test_bootstrap_definer_has_no_role_memberships(admin_conn: PgConnection) -> None:
    rows = admin_conn.execute(
        """
        SELECT parent.rolname, member.rolname
          FROM pg_auth_members membership
          JOIN pg_roles parent ON parent.oid = membership.roleid
          JOIN pg_roles member ON member.oid = membership.member
         WHERE parent.rolname = %s OR member.rolname = %s
        """,
        (_ROLE, _ROLE),
    ).fetchall()
    assert rows == []


def test_bootstrap_definer_has_exact_schema_authority(admin_conn: PgConnection) -> None:
    rows = admin_conn.execute(
        """
        SELECT nspname,
               has_schema_privilege(%s, oid, 'USAGE'),
               has_schema_privilege(%s, oid, 'CREATE')
          FROM pg_namespace
         WHERE nspname IN ('request_engine', 'request_platform')
         ORDER BY nspname
        """,
        (_ROLE, _ROLE),
    ).fetchall()
    assert rows == [
        ("request_engine", True, False),
        ("request_platform", True, False),
    ]


def test_bootstrap_definer_has_only_reviewed_column_authority(
    admin_conn: PgConnection,
) -> None:
    rows = admin_conn.execute(
        """
        SELECT table_name, column_name, privilege_type
          FROM information_schema.column_privileges
         WHERE grantee = %s AND table_schema = 'request_engine'
         ORDER BY table_name, column_name, privilege_type
        """,
        (_ROLE,),
    ).fetchall()
    actual = {
        (cast(str, table), cast(str, column), cast(str, privilege))
        for table, column, privilege in rows
    }
    assert actual == _EXPECTED_COLUMNS

    table_grants = admin_conn.execute(
        """
        SELECT table_name, privilege_type
          FROM information_schema.role_table_grants
         WHERE grantee = %s AND table_schema = 'request_engine'
        """,
        (_ROLE,),
    ).fetchall()
    assert table_grants == []


def test_bootstrap_definer_owns_only_root_establishment_function(
    admin_conn: PgConnection,
) -> None:
    rows = admin_conn.execute(
        """
        SELECT namespace.nspname, procedure.proname,
               pg_get_function_identity_arguments(procedure.oid)
          FROM pg_proc procedure
          JOIN pg_namespace namespace ON namespace.oid = procedure.pronamespace
          JOIN pg_roles owner_role ON owner_role.oid = procedure.proowner
         WHERE owner_role.rolname = %s
         ORDER BY namespace.nspname, procedure.proname
        """,
        (_ROLE,),
    ).fetchall()
    assert rows == [
        (
            "request_platform",
            "establish_root",
            "p_intent_id uuid, p_token_digest bytea, p_identity_authority_id uuid, "
            "p_native_identity_id uuid, p_login_handle text, p_credential_id uuid, "
            "p_password_verifier text, p_principal_id uuid, p_binding_id uuid",
        )
    ]
