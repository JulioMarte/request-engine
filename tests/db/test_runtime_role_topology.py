from typing import Any, cast

import pytest
from psycopg import Connection

PgConnection = Connection[Any]

pytestmark = [pytest.mark.postgres, pytest.mark.invariant, pytest.mark.adversarial]

_RUNTIME_SCHEMAS = ("request_engine", "request_read", "request_cmd", "request_admin")
_DATABASE_ROLES = {
    "request_engine_admin": (False, False, True, False, False),
    "request_engine_app": (False, False, False, False, False),
    "request_engine_discovery": (False, False, False, False, False),
    "request_engine_discovery_definer": (False, False, True, False, False),
    "request_engine_schema_owner": (False, False, False, False, False),
    "request_engine_worker": (False, False, False, False, False),
}
_EXPECTED_SCHEMA_USAGE = {
    "request_engine_app": {"request_engine", "request_read", "request_cmd"},
    "request_engine_discovery": {"request_engine"},
    "request_engine_worker": {"request_engine", "request_cmd"},
    "request_engine_admin": set(_RUNTIME_SCHEMAS),
    "request_engine_discovery_definer": {"request_engine"},
}
_RUNTIME_GROUP_ROLES = {
    "request_engine_admin",
    "request_engine_app",
    "request_engine_discovery",
    "request_engine_worker",
}
_DISCOVERY_DEFINER_RELATION_PRIVILEGES = {
    ("discovery_booking_handoffs", "INSERT"),
    ("discovery_booking_handoffs", "SELECT"),
    ("discovery_booking_handoffs", "UPDATE"),
    ("discovery_publications", "SELECT"),
    ("locations", "SELECT"),
    ("offering_service_classifications", "SELECT"),
    ("offering_versions", "SELECT"),
    ("offerings", "SELECT"),
    ("organizations", "SELECT"),
    ("resource_public_profiles", "SELECT"),
    ("resources", "SELECT"),
    ("service_classifications", "SELECT"),
}
_DISCOVERY_DEFINER_COLUMN_PRIVILEGES = {
    ("discovery_publications", "id", "UPDATE"),
    ("offering_service_classifications", "id", "UPDATE"),
    ("offerings", "id", "UPDATE"),
}
_DISCOVERY_DEFINER_FUNCTIONS = {
    "current_organization_id()",
    "guard_discovery_handoff_latest_version()",
    "guard_discovery_handoff_reservation()",
    "has_active_discovery_mapping(uuid)",
    (
        "issue_discovery_booking_handoff(text, uuid, bigint, uuid, bigint, uuid, uuid, jsonb, "
        "timestamp with time zone)"
    ),
    "read_discovery_booking_handoff(text)",
    (
        "search_discovery_candidates_v2(text, double precision, double precision, integer, "
        "timestamp with time zone, timestamp with time zone, integer)"
    ),
}


@pytest.mark.postgres
def test_database_roles_are_nonlogin_and_have_reviewed_elevation(
    admin_conn: PgConnection,
) -> None:
    rows = admin_conn.execute(
        """
        SELECT rolname, rolcanlogin, rolsuper, rolbypassrls, rolcreatedb, rolcreaterole
        FROM pg_roles
        WHERE rolname = ANY(%s)
        ORDER BY rolname
        """,
        (sorted(_DATABASE_ROLES),),
    ).fetchall()

    actual = {
        cast(str, name): (
            cast(bool, can_login),
            cast(bool, superuser),
            cast(bool, bypass_rls),
            cast(bool, create_db),
            cast(bool, create_role),
        )
        for name, can_login, superuser, bypass_rls, create_db, create_role in rows
    }
    assert actual == _DATABASE_ROLES


@pytest.mark.postgres
def test_runtime_and_definer_roles_have_only_intended_schema_usage(
    admin_conn: PgConnection,
) -> None:
    for role, expected_usage in _EXPECTED_SCHEMA_USAGE.items():
        rows = admin_conn.execute(
            """
            SELECT nspname,
                   has_schema_privilege(%s, oid, 'USAGE'),
                   has_schema_privilege(%s, oid, 'CREATE')
            FROM pg_namespace
            WHERE nspname = ANY(%s)
            ORDER BY nspname
            """,
            (role, role, list(_RUNTIME_SCHEMAS)),
        ).fetchall()
        usage = {cast(str, name) for name, can_use, _ in rows if can_use}
        assert usage == expected_usage
        assert all(not cast(bool, can_create) for _, _, can_create in rows)


@pytest.mark.postgres
def test_request_engine_roles_do_not_inherit_one_another(admin_conn: PgConnection) -> None:
    rows = admin_conn.execute(
        """
        SELECT parent.rolname, member.rolname
        FROM pg_auth_members membership
        JOIN pg_roles parent ON parent.oid = membership.roleid
        JOIN pg_roles member ON member.oid = membership.member
        WHERE parent.rolname LIKE 'request_engine\\_%' ESCAPE '\\'
          AND member.rolname LIKE 'request_engine\\_%' ESCAPE '\\'
        ORDER BY parent.rolname, member.rolname
        """
    ).fetchall()

    assert rows == []


@pytest.mark.postgres
def test_runtime_group_roles_own_no_application_schema_objects(
    admin_conn: PgConnection,
) -> None:
    relation_rows = admin_conn.execute(
        """
        SELECT n.nspname, c.relname, pg_get_userbyid(c.relowner)
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = ANY(%s)
          AND pg_get_userbyid(c.relowner) = ANY(%s)
        ORDER BY n.nspname, c.relname
        """,
        (list(_RUNTIME_SCHEMAS), sorted(_RUNTIME_GROUP_ROLES)),
    ).fetchall()
    routine_rows = admin_conn.execute(
        """
        SELECT n.nspname, p.proname, pg_get_userbyid(p.proowner)
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = ANY(%s)
          AND pg_get_userbyid(p.proowner) = ANY(%s)
        ORDER BY n.nspname, p.proname
        """,
        (list(_RUNTIME_SCHEMAS), sorted(_RUNTIME_GROUP_ROLES)),
    ).fetchall()

    assert relation_rows == []
    assert routine_rows == []


@pytest.mark.postgres
def test_discovery_definer_has_exact_relation_privileges(admin_conn: PgConnection) -> None:
    rows = admin_conn.execute(
        """
        SELECT c.relname, acl.privilege_type
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        CROSS JOIN LATERAL aclexplode(
            COALESCE(c.relacl, acldefault('r', c.relowner))
        ) AS acl
        WHERE n.nspname = 'request_engine'
          AND c.relkind IN ('r','p','v','m')
          AND acl.grantee = (
              SELECT oid FROM pg_roles
              WHERE rolname = 'request_engine_discovery_definer'
          )
        ORDER BY c.relname, acl.privilege_type
        """
    ).fetchall()

    actual = {(cast(str, relation), cast(str, privilege)) for relation, privilege in rows}
    assert actual == _DISCOVERY_DEFINER_RELATION_PRIVILEGES


@pytest.mark.postgres
def test_discovery_definer_has_exact_column_lock_privileges(admin_conn: PgConnection) -> None:
    rows = admin_conn.execute(
        """
        SELECT c.relname, a.attname, acl.privilege_type
        FROM pg_attribute a
        JOIN pg_class c ON c.oid = a.attrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        CROSS JOIN LATERAL aclexplode(a.attacl) AS acl
        WHERE n.nspname = 'request_engine'
          AND a.attnum > 0
          AND NOT a.attisdropped
          AND acl.grantee = (
              SELECT oid FROM pg_roles
              WHERE rolname = 'request_engine_discovery_definer'
          )
        ORDER BY c.relname, a.attname, acl.privilege_type
        """
    ).fetchall()

    actual = {
        (cast(str, relation), cast(str, column), cast(str, privilege))
        for relation, column, privilege in rows
    }
    assert actual == _DISCOVERY_DEFINER_COLUMN_PRIVILEGES


@pytest.mark.postgres
def test_discovery_definer_has_exact_function_authority(admin_conn: PgConnection) -> None:
    rows = admin_conn.execute(
        """
        SELECT p.proname, oidvectortypes(p.proargtypes)
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = ANY(%s)
          AND has_schema_privilege(
              'request_engine_discovery_definer', n.oid, 'USAGE'
          )
          AND has_function_privilege(
              'request_engine_discovery_definer', p.oid, 'EXECUTE'
          )
        ORDER BY p.proname, oidvectortypes(p.proargtypes)
        """,
        (list(_RUNTIME_SCHEMAS),),
    ).fetchall()

    actual = {f"{cast(str, name)}({cast(str, arguments)})" for name, arguments in rows}
    assert actual == _DISCOVERY_DEFINER_FUNCTIONS


@pytest.mark.postgres
def test_worker_has_no_direct_relation_privileges(admin_conn: PgConnection) -> None:
    rows = admin_conn.execute(
        """
        SELECT n.nspname, c.relname, acl.privilege_type
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        CROSS JOIN LATERAL aclexplode(
            COALESCE(c.relacl, acldefault('r', c.relowner))
        ) AS acl
        WHERE n.nspname = ANY(%s)
          AND c.relkind IN ('r','p','v','m')
          AND acl.grantee = (
              SELECT oid FROM pg_roles WHERE rolname = 'request_engine_worker'
          )
        ORDER BY n.nspname, c.relname, acl.privilege_type
        """,
        (list(_RUNTIME_SCHEMAS),),
    ).fetchall()

    assert rows == []
