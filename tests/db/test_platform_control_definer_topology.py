from typing import Any, cast

import pytest
from psycopg import Connection

PgConnection = Connection[Any]
pytestmark = [pytest.mark.postgres, pytest.mark.invariant, pytest.mark.security]

_RUNTIME = "request_platform_control"
_DEFINER = "request_platform_control_definer"
_PROVISIONER_FUNCTION = "request_platform.provision_tenant_provisioner(uuid, text, text)"
_ROOT_FUNCTION = (
    "request_platform.provision_native_organization_root(uuid, text, text, uuid, uuid, "
    "uuid, uuid, text)"
)
_OLD_ORGANIZATION_FUNCTION = "request_platform.provision_organization(uuid, text, text, text)"
_EXPECTED_COLUMNS = {
    ("identity_authorities", "id", "SELECT"),
    ("identity_authorities", "kind", "SELECT"),
    ("identity_authorities", "status", "SELECT"),
    ("identity_bindings", "id", "INSERT"),
    ("identity_bindings", "organization_id", "INSERT"),
    ("identity_bindings", "principal_id", "INSERT"),
    ("identity_bindings", "principal_plane", "INSERT"),
    ("identity_bindings", "identity_authority_id", "INSERT"),
    ("identity_bindings", "subject_id", "INSERT"),
    ("identity_bindings", "status", "INSERT"),
    ("native_credentials", "native_identity_id", "SELECT"),
    ("native_credentials", "kind", "SELECT"),
    ("native_credentials", "status", "SELECT"),
    ("native_identities", "id", "SELECT"),
    ("native_identities", "identity_authority_id", "SELECT"),
    ("native_identities", "status", "SELECT"),
    ("organization_provisioning_facts", "organization_id", "INSERT"),
    ("organization_provisioning_facts", "provisioned_by_principal_id", "INSERT"),
    ("organization_provisioning_facts", "provenance_reference", "INSERT"),
    ("organization_root_provisioning_facts", "organization_id", "SELECT"),
    ("organization_root_provisioning_facts", "organization_party_id", "SELECT"),
    ("organization_root_provisioning_facts", "controller_principal_id", "SELECT"),
    ("organization_root_provisioning_facts", "controller_binding_id", "SELECT"),
    ("organization_root_provisioning_facts", "provisioned_by_principal_id", "SELECT"),
    ("organization_root_provisioning_facts", "provenance_reference", "SELECT"),
    ("organization_root_provisioning_facts", "organization_id", "INSERT"),
    ("organization_root_provisioning_facts", "organization_party_id", "INSERT"),
    ("organization_root_provisioning_facts", "controller_principal_id", "INSERT"),
    ("organization_root_provisioning_facts", "controller_binding_id", "INSERT"),
    ("organization_root_provisioning_facts", "provisioned_by_principal_id", "INSERT"),
    ("organization_root_provisioning_facts", "provenance_reference", "INSERT"),
    ("organizations", "id", "INSERT"),
    ("organizations", "organization_key", "INSERT"),
    ("organizations", "display_name", "INSERT"),
    ("parties", "id", "INSERT"),
    ("parties", "organization_id", "INSERT"),
    ("parties", "party_kind", "INSERT"),
    ("parties", "display_name", "INSERT"),
    ("parties", "created_by_principal_id", "INSERT"),
    ("parties", "source_kind", "INSERT"),
    ("parties", "platform", "INSERT"),
    ("party_identity_revisions", "organization_id", "INSERT"),
    ("party_identity_revisions", "party_id", "INSERT"),
    ("party_identity_revisions", "revision", "INSERT"),
    ("party_identity_revisions", "change_kind", "INSERT"),
    ("party_identity_revisions", "display_name", "INSERT"),
    ("party_identity_revisions", "active", "INSERT"),
    ("party_identity_revisions", "state", "INSERT"),
    ("party_identity_revisions", "actor_principal_id", "INSERT"),
    ("party_identity_revisions", "attributed_operator_principal_id", "INSERT"),
    ("party_identity_revisions", "source_kind", "INSERT"),
    ("party_identity_revisions", "platform", "INSERT"),
    ("principals", "id", "SELECT"),
    ("principals", "organization_id", "SELECT"),
    ("principals", "principal_plane", "SELECT"),
    ("principals", "principal_kind", "SELECT"),
    ("principals", "active", "SELECT"),
    ("principals", "authority_revision", "SELECT"),
    ("principals", "id", "INSERT"),
    ("principals", "organization_id", "INSERT"),
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
    ("principal_authority_grants", "organization_id", "INSERT"),
    ("principal_authority_grants", "principal_id", "INSERT"),
    ("principal_authority_grants", "principal_plane", "INSERT"),
    ("principal_authority_grants", "authority_plane", "INSERT"),
    ("principal_authority_grants", "capability_key", "INSERT"),
    ("principal_authority_grants", "delegable", "INSERT"),
    ("principal_authority_grants", "granted_by_principal_id", "INSERT"),
    ("principal_authority_grants", "provenance_kind", "INSERT"),
    ("principal_authority_grants", "provenance_reference", "INSERT"),
    ("representations", "organization_id", "INSERT"),
    ("representations", "principal_id", "INSERT"),
    ("representations", "represented_party_id", "INSERT"),
    ("representations", "authority_kind", "INSERT"),
    ("representations", "scope_key", "INSERT"),
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
    assert (
        admin_conn.execute(
            """
            SELECT table_name, privilege_type
              FROM information_schema.role_table_grants
             WHERE grantee = %s AND table_schema = 'request_engine'
            """,
            (_DEFINER,),
        ).fetchall()
        == []
    )


def test_only_platform_control_runtime_can_execute_commands(
    admin_conn: PgConnection,
) -> None:
    for function in (_PROVISIONER_FUNCTION, _ROOT_FUNCTION):
        assert admin_conn.execute(
            "SELECT has_function_privilege(%s, %s, 'EXECUTE')",
            (_RUNTIME, function),
        ).fetchone() == (True,)
        assert admin_conn.execute(
            "SELECT has_function_privilege('request_engine_app', %s, 'EXECUTE')",
            (function,),
        ).fetchone() == (False,)
        assert admin_conn.execute(
            "SELECT has_function_privilege('public', %s, 'EXECUTE')",
            (function,),
        ).fetchone() == (False,)

    assert admin_conn.execute(
        "SELECT to_regprocedure(%s)",
        (_OLD_ORGANIZATION_FUNCTION,),
    ).fetchone() == (None,)
