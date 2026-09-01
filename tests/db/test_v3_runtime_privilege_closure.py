from collections.abc import Generator
from contextlib import contextmanager
from typing import Any, cast
from uuid import uuid4

import psycopg
import pytest
from psycopg import Connection, sql
from psycopg.errors import InsufficientPrivilege
from runtime_role_function_surface import EXPECTED_FUNCTIONS

PgConnection = Connection[Any]

PRIVATE_GLOBAL_TABLES = {
    "global_identities",
    "shared_capacity_authority_events",
    "shared_capacity_bindings",
    "shared_capacity_claim_links",
    "shared_capacity_identities",
}

DEFINER_MEDIATED_TABLES = {
    "discovery_booking_handoffs",
    "service_classification_authority_events",
}

# F2 taxonomy/discovery tables follow reviewed narrower-than-generic shapes:
# taxonomy is read through definer functions, the authority-event ledger is
# append-only and definer-written, and handoffs are fully definer-mediated.
EXPECTED_RELATION_PRIVILEGE_OVERRIDES: dict[tuple[str, str, str], set[str]] = {
    ("request_engine_app", "request_engine", "service_classifications"): {
        "INSERT",
        "UPDATE",
    },
    ("request_engine_app", "request_engine", "discovery_booking_handoffs"): set(),
    (
        "request_engine_app",
        "request_engine",
        "service_classification_authority_events",
    ): set(),
    # F4 recomputes assignment availability, which legitimately deletes stale rows.
    (
        "request_engine_app",
        "request_engine",
        "resource_location_availability",
    ): {"SELECT", "INSERT", "UPDATE", "DELETE"},
    # S0b2 (§9.3): the party identity revision ledger is append-only for the
    # app role; UPDATE/DELETE are denied by grants and by the 0025 guard.
    ("request_engine_app", "request_engine", "party_identity_revisions"): {
        "SELECT",
        "INSERT",
    },
    ("request_engine_admin", "request_engine", "service_classifications"): {
        "SELECT",
        "REFERENCES",
        "TRIGGER",
        "MAINTAIN",
    },
    (
        "request_engine_admin",
        "request_engine",
        "service_classification_authority_events",
    ): {"SELECT"},
}

ALL_TABLE_PRIVILEGES = {
    "SELECT",
    "INSERT",
    "UPDATE",
    "DELETE",
    "TRUNCATE",
    "REFERENCES",
    "TRIGGER",
    "MAINTAIN",
}

EXPECTED_SCHEMAS = {
    "request_engine_app": {"request_engine", "request_read", "request_cmd"},
    "request_engine_worker": {"request_engine", "request_cmd"},
    "request_engine_admin": {
        "request_engine",
        "request_read",
        "request_cmd",
        "request_admin",
    },
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
    role_name = f"{group_role}_closure_{uuid4().hex[:16]}"
    password = uuid4().hex
    admin_conn.execute(
        sql.SQL(
            "CREATE ROLE {} LOGIN INHERIT NOBYPASSRLS NOSUPERUSER "
            "NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD {}"
        ).format(sql.Identifier(role_name), sql.Literal(password))
    )
    admin_conn.execute(
        sql.SQL("GRANT {} TO {} WITH INHERIT TRUE").format(
            sql.Identifier(group_role),
            sql.Identifier(role_name),
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


def _function_surface(conn: PgConnection) -> set[str]:
    rows = conn.execute(
        """
        SELECT n.nspname, p.proname, oidvectortypes(p.proargtypes)
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname IN ('request_engine', 'request_cmd', 'request_admin')
          AND has_schema_privilege(current_user, n.oid, 'USAGE')
          AND has_function_privilege(current_user, p.oid, 'EXECUTE')
        ORDER BY n.nspname, p.proname, oidvectortypes(p.proargtypes)
        """
    ).fetchall()
    return {
        f"{cast(str, schema)}.{cast(str, name)}({cast(str, arguments)})"
        for schema, name, arguments in rows
    }


def _relation_privileges(conn: PgConnection, relation_oid: int) -> set[str]:
    return {
        privilege
        for privilege in ALL_TABLE_PRIVILEGES
        if conn.execute(
            "SELECT has_table_privilege(current_user, %s::oid, %s)",
            (relation_oid, privilege),
        ).fetchone()
        == (True,)
    }


def _expected_relation_privileges(group_role: str, schema: str, name: str) -> set[str]:
    override = EXPECTED_RELATION_PRIVILEGE_OVERRIDES.get((group_role, schema, name))
    if override is not None:
        return override
    if group_role == "request_engine_worker":
        return set()
    if group_role == "request_engine_app":
        if schema == "request_engine":
            if name in PRIVATE_GLOBAL_TABLES or name in DEFINER_MEDIATED_TABLES:
                return set()
            return {"SELECT", "INSERT", "UPDATE"}
        if schema == "request_read":
            return {"SELECT"}
        return set()
    if schema == "request_engine":
        if name in PRIVATE_GLOBAL_TABLES:
            return {"SELECT"}
        return ALL_TABLE_PRIVILEGES
    if schema in {"request_read", "request_admin"}:
        return {"SELECT"}
    return set()


@pytest.mark.postgres
@pytest.mark.parametrize(
    "group_role",
    ["request_engine_app", "request_engine_worker", "request_engine_admin"],
)
def test_real_runtime_logins_match_complete_schema_relation_and_function_contract(
    admin_conn: PgConnection,
    pg_conninfo: str,
    group_role: str,
) -> None:
    with _runtime_login(admin_conn, pg_conninfo, group_role) as runtime:
        identity = runtime.execute(
            """
            SELECT current_user = session_user,
                   rolsuper,
                   rolbypassrls,
                   rolcreatedb,
                   rolcreaterole
            FROM pg_roles
            WHERE rolname = current_user
            """
        ).fetchone()
        assert identity == (True, False, False, False, False)

        schema_rows = runtime.execute(
            """
            SELECT nspname,
                   has_schema_privilege(current_user, oid, 'USAGE'),
                   has_schema_privilege(current_user, oid, 'CREATE')
            FROM pg_namespace
            WHERE nspname IN ('request_engine', 'request_read', 'request_cmd', 'request_admin')
            ORDER BY nspname
            """
        ).fetchall()
        usable = {cast(str, name) for name, usage, _ in schema_rows if usage}
        assert usable == EXPECTED_SCHEMAS[group_role]
        assert all(not create for _, _, create in schema_rows)

        relations = runtime.execute(
            """
            SELECT c.oid, n.nspname, c.relname
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname IN ('request_engine', 'request_read', 'request_admin')
              AND c.relkind IN ('r', 'p', 'v', 'm')
            ORDER BY n.nspname, c.relname
            """
        ).fetchall()
        assert relations
        for relation_oid, schema, name in relations:
            schema_name = cast(str, schema)
            relation_name = cast(str, name)
            assert _relation_privileges(runtime, cast(int, relation_oid)) == (
                _expected_relation_privileges(group_role, schema_name, relation_name)
            )

        assert _function_surface(runtime) == EXPECTED_FUNCTIONS[group_role]

        probe = f"g14_probe_{uuid4().hex[:16]}"
        runtime.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(group_role)))
        own_role = runtime.execute(
            "SELECT current_user, rolbypassrls FROM pg_roles WHERE rolname = current_user"
        ).fetchone()
        assert own_role == (group_role, group_role == "request_engine_admin")
        with pytest.raises(InsufficientPrivilege):
            runtime.execute(
                sql.SQL("CREATE TABLE request_engine.{} (id integer)").format(sql.Identifier(probe))
            )
        runtime.execute("RESET ROLE")

        for forbidden_role in (
            {"request_engine_app", "request_engine_worker", "request_engine_admin"} - {group_role}
        ) | {"request_engine_schema_owner"}:
            with pytest.raises(InsufficientPrivilege):
                runtime.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(forbidden_role)))


@pytest.mark.postgres
def test_core_roles_and_all_security_definers_are_hardened(admin_conn: PgConnection) -> None:
    role_rows = admin_conn.execute(
        """
        SELECT rolname, rolcanlogin, rolsuper, rolbypassrls, rolcreatedb, rolcreaterole
        FROM pg_roles
        WHERE rolname IN (
            'request_engine_schema_owner',
            'request_engine_app',
            'request_engine_worker',
            'request_engine_admin'
        )
        ORDER BY rolname
        """
    ).fetchall()
    assert role_rows == [
        ("request_engine_admin", False, False, True, False, False),
        ("request_engine_app", False, False, False, False, False),
        ("request_engine_schema_owner", False, False, False, False, False),
        ("request_engine_worker", False, False, False, False, False),
    ]

    memberships = admin_conn.execute(
        """
        SELECT granted.rolname, member.rolname
        FROM pg_auth_members m
        JOIN pg_roles granted ON granted.oid = m.roleid
        JOIN pg_roles member ON member.oid = m.member
        WHERE granted.rolname LIKE 'request_engine_%'
          AND member.rolname LIKE 'request_engine_%'
        ORDER BY granted.rolname, member.rolname
        """
    ).fetchall()
    assert memberships == []

    definers = admin_conn.execute(
        """
        SELECT n.nspname,
               p.proname,
               pg_get_function_identity_arguments(p.oid),
               owner.rolname,
               p.proconfig,
               EXISTS (
                   SELECT 1
                   FROM aclexplode(COALESCE(p.proacl, acldefault('f', p.proowner))) acl
                   WHERE acl.grantee = 0
                     AND acl.privilege_type = 'EXECUTE'
               ) AS public_execute
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        JOIN pg_roles owner ON owner.oid = p.proowner
        WHERE n.nspname IN ('request_engine', 'request_cmd', 'request_admin')
          AND p.prosecdef
        ORDER BY n.nspname, p.proname, pg_get_function_identity_arguments(p.oid)
        """
    ).fetchall()
    assert definers
    for schema, name, arguments, owner, config, public_execute in definers:
        assert cast(str, schema) in {"request_engine", "request_cmd", "request_admin"}
        assert cast(str, name)
        assert cast(str, arguments) is not None
        assert owner in {"request_engine_schema_owner", "request_engine_admin"}
        assert config == ["search_path=pg_catalog, request_engine, pg_temp"]
        assert public_execute is False
