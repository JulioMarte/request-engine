from typing import Any, cast

import pytest
from psycopg import Connection

PgConnection = Connection[Any]
pytestmark = [
    pytest.mark.postgres,
    pytest.mark.invariant,
    pytest.mark.adversarial,
    pytest.mark.security,
]

_ROLE = "request_platform_definer"
_APPLICATION_SCHEMAS = [
    "request_admin",
    "request_auth",
    "request_cmd",
    "request_engine",
    "request_platform",
    "request_read",
]
_EXPECTED_COLUMN_PRIVILEGES = {
    ("identity_bindings", "id", "SELECT"),
    ("identity_bindings", "identity_authority_id", "SELECT"),
    ("identity_bindings", "subject_id", "SELECT"),
    ("identity_bindings", "principal_id", "SELECT"),
    ("identity_bindings", "principal_plane", "SELECT"),
    ("identity_bindings", "organization_id", "SELECT"),
    ("identity_bindings", "status", "SELECT"),
    ("identity_bindings", "revision", "SELECT"),
    ("principal_authority_grants", "authority_plane", "SELECT"),
    ("principal_authority_grants", "capability_key", "SELECT"),
    ("principal_authority_grants", "delegable", "SELECT"),
    ("principal_authority_grants", "granted_at", "SELECT"),
    ("principal_authority_grants", "principal_id", "SELECT"),
    ("principal_authority_grants", "principal_plane", "SELECT"),
    ("principal_authority_grants", "provenance_kind", "SELECT"),
    ("principal_authority_grants", "provenance_reference", "SELECT"),
    ("principal_authority_grants", "status", "SELECT"),
    ("principals", "active", "SELECT"),
    ("principals", "authority_revision", "SELECT"),
    ("principals", "id", "SELECT"),
    ("principals", "principal_kind", "SELECT"),
    ("principals", "principal_plane", "SELECT"),
    ("identity_recovery_cases", "approval_expires_at", "SELECT"),
    ("identity_recovery_cases", "approved_at", "SELECT"),
    ("identity_recovery_cases", "consumed_at", "SELECT"),
    ("identity_recovery_cases", "created_at", "SELECT"),
    ("identity_recovery_cases", "delivery_status", "SELECT"),
    ("identity_recovery_cases", "id", "SELECT"),
    ("identity_recovery_cases", "issuance_generation", "SELECT"),
    ("identity_recovery_cases", "issued_at", "SELECT"),
    ("identity_recovery_cases", "proof_expires_at", "SELECT"),
    ("identity_recovery_cases", "revision", "SELECT"),
    ("identity_recovery_cases", "revoked_at", "SELECT"),
    ("identity_recovery_cases", "status", "SELECT"),
    ("identity_recovery_cases", "target_native_identity_id", "SELECT"),
    ("native_identities", "id", "SELECT"),
    ("native_identities", "identity_authority_id", "SELECT"),
    ("native_identities", "status", "SELECT"),
    ("native_identities", "revision", "SELECT"),
    ("native_identities", "created_at", "SELECT"),
    ("native_identities", "disabled_at", "SELECT"),
    ("platform_configuration_revisions", "id", "SELECT"),
    ("platform_configuration_revisions", "configuration_kind", "SELECT"),
    ("platform_configuration_revisions", "provider_kind", "SELECT"),
    ("platform_configuration_revisions", "revision", "SELECT"),
    ("platform_configuration_revisions", "configuration", "SELECT"),
    ("platform_configuration_revisions", "secret_binding_id", "SELECT"),
    ("platform_configuration_revisions", "state", "SELECT"),
    ("platform_configuration_revisions", "created_by_principal_id", "SELECT"),
    ("platform_configuration_revisions", "created_at", "SELECT"),
    ("platform_configuration_revisions", "validated_at", "SELECT"),
    ("platform_configuration_revisions", "activated_at", "SELECT"),
    ("platform_configuration_revisions", "disabled_at", "SELECT"),
    ("platform_secret_bindings", "id", "SELECT"),
    ("platform_secret_bindings", "purpose", "SELECT"),
    ("platform_secret_bindings", "backend", "SELECT"),
    ("platform_secret_bindings", "backend_version", "SELECT"),
    ("platform_secret_bindings", "status", "SELECT"),
    ("platform_secret_bindings", "revision", "SELECT"),
    ("platform_secret_bindings", "created_at", "SELECT"),
    ("platform_secret_bindings", "rotated_at", "SELECT"),
    ("platform_secret_bindings", "revoked_at", "SELECT"),
}


def test_platform_definer_has_exact_role_elevation(admin_conn: PgConnection) -> None:
    row = admin_conn.execute(
        """
        SELECT rolcanlogin, rolsuper, rolbypassrls, rolcreatedb, rolcreaterole,
               rolreplication, rolinherit, rolconnlimit, rolvaliduntil,
               rolpassword IS NOT NULL
        FROM pg_authid
        WHERE rolname = %s
        """,
        (_ROLE,),
    ).fetchone()

    assert row == (False, False, True, False, False, False, True, -1, None, False)


def test_platform_definer_does_not_collide_with_accepted_baseline_role_namespace() -> None:
    assert not _ROLE.startswith("request_engine_")


def test_platform_definer_has_no_role_memberships(admin_conn: PgConnection) -> None:
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


def test_platform_definer_has_exact_schema_authority(admin_conn: PgConnection) -> None:
    rows = admin_conn.execute(
        """
        SELECT nspname,
               has_schema_privilege(%s, oid, 'USAGE'),
               has_schema_privilege(%s, oid, 'CREATE')
        FROM pg_namespace
        WHERE nspname = ANY(%s)
        ORDER BY nspname
        """,
        (_ROLE, _ROLE, _APPLICATION_SCHEMAS),
    ).fetchall()

    actual = {cast(str, name): (bool(usage), bool(create)) for name, usage, create in rows}
    assert actual == {
        "request_admin": (False, False),
        "request_auth": (True, False),
        "request_cmd": (False, False),
        "request_engine": (True, False),
        "request_platform": (True, False),
        "request_read": (False, False),
    }


def test_platform_definer_has_only_reviewed_column_reads(admin_conn: PgConnection) -> None:
    table_grants = admin_conn.execute(
        """
        SELECT c.relname, acl.privilege_type
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        CROSS JOIN LATERAL aclexplode(c.relacl) AS acl
        WHERE n.nspname = 'request_engine'
          AND acl.grantee = (SELECT oid FROM pg_roles WHERE rolname = %s)
        ORDER BY c.relname, acl.privilege_type
        """,
        (_ROLE,),
    ).fetchall()
    assert table_grants == []

    column_grants = admin_conn.execute(
        """
        SELECT c.relname, a.attname, acl.privilege_type
        FROM pg_attribute a
        JOIN pg_class c ON c.oid = a.attrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        CROSS JOIN LATERAL aclexplode(a.attacl) AS acl
        WHERE n.nspname = 'request_engine'
          AND a.attnum > 0
          AND NOT a.attisdropped
          AND acl.grantee = (SELECT oid FROM pg_roles WHERE rolname = %s)
        ORDER BY c.relname, a.attname, acl.privilege_type
        """,
        (_ROLE,),
    ).fetchall()
    actual = {
        (cast(str, relation), cast(str, column), cast(str, privilege))
        for relation, column, privilege in column_grants
    }
    assert actual == _EXPECTED_COLUMN_PRIVILEGES


def test_platform_definer_owns_only_platform_read_boundary(admin_conn: PgConnection) -> None:
    relations = admin_conn.execute(
        """
        SELECT n.nspname, c.relname
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = ANY(%s)
          AND pg_get_userbyid(c.relowner) = %s
        ORDER BY n.nspname, c.relname
        """,
        (_APPLICATION_SCHEMAS, _ROLE),
    ).fetchall()
    assert relations == []

    routines = admin_conn.execute(
        """
        SELECT n.nspname, p.proname, pg_get_function_identity_arguments(p.oid),
               p.prosecdef, p.proconfig
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = ANY(%s)
          AND pg_get_userbyid(p.proowner) = %s
        ORDER BY n.nspname, p.proname
        """,
        (_APPLICATION_SCHEMAS, _ROLE),
    ).fetchall()
    assert routines == [
        (
            "request_auth",
            "read_platform_identity_bindings",
            "p_identity_authority_id uuid, p_subject_id text",
            True,
            ["search_path=pg_catalog, request_engine, pg_temp"],
        ),
        (
            "request_platform",
            "read_identity_recovery_cases",
            "p_case_id uuid, p_after uuid, p_limit integer",
            True,
            ["search_path=pg_catalog, request_engine, pg_temp"],
        ),
        (
            "request_platform",
            "read_native_identities",
            "p_identity_id uuid, p_after uuid, p_limit integer",
            True,
            ["search_path=pg_catalog, request_engine, pg_temp"],
        ),
        (
            "request_platform",
            "read_platform_configuration_revisions",
            "p_configuration_kind text",
            True,
            ["search_path=pg_catalog, request_engine, pg_temp"],
        ),
        (
            "request_platform",
            "read_platform_provisioners",
            "p_principal_id uuid, p_after uuid, p_limit integer",
            True,
            ["search_path=pg_catalog, request_engine, pg_temp"],
        ),
        (
            "request_platform",
            "read_platform_secret_binding",
            "p_binding_id uuid",
            True,
            ["search_path=pg_catalog, request_engine, pg_temp"],
        ),
        (
            "request_platform",
            "read_principal_authority",
            "p_principal_id uuid",
            True,
            ["search_path=pg_catalog, request_engine, pg_temp"],
        ),
    ]
