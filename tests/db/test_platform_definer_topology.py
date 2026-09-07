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

_ROLE = "request_engine_platform_definer"
_EXPECTED_COLUMN_PRIVILEGES = {
    ("principal_authority_grants", "authority_plane", "SELECT"),
    ("principal_authority_grants", "capability_key", "SELECT"),
    ("principal_authority_grants", "delegable", "SELECT"),
    ("principal_authority_grants", "principal_id", "SELECT"),
    ("principal_authority_grants", "principal_plane", "SELECT"),
    ("principal_authority_grants", "status", "SELECT"),
    ("principals", "active", "SELECT"),
    ("principals", "authority_revision", "SELECT"),
    ("principals", "id", "SELECT"),
    ("principals", "principal_kind", "SELECT"),
    ("principals", "principal_plane", "SELECT"),
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
        (
            _ROLE,
            _ROLE,
            ["request_admin", "request_cmd", "request_engine", "request_platform", "request_read"],
        ),
    ).fetchall()

    actual = {cast(str, name): (bool(usage), bool(create)) for name, usage, create in rows}
    assert actual == {
        "request_admin": (False, False),
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
        WHERE n.nspname LIKE 'request_%'
          AND pg_get_userbyid(c.relowner) = %s
        ORDER BY n.nspname, c.relname
        """,
        (_ROLE,),
    ).fetchall()
    assert relations == []

    routines = admin_conn.execute(
        """
        SELECT n.nspname, p.proname, pg_get_function_identity_arguments(p.oid),
               p.prosecdef, p.proconfig
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname LIKE 'request_%'
          AND pg_get_userbyid(p.proowner) = %s
        ORDER BY n.nspname, p.proname
        """,
        (_ROLE,),
    ).fetchall()
    assert routines == [
        (
            "request_platform",
            "read_principal_authority",
            "p_principal_id uuid",
            True,
            ["search_path=pg_catalog, request_engine, pg_temp"],
        )
    ]
