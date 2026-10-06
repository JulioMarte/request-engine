from __future__ import annotations

import os
import subprocess
from typing import Any
from urllib.parse import quote_plus
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo


def _verify_native_receipt_privileges(connection: psycopg.Connection[Any]) -> None:
    """Independent current-contract oracle for upgrade/fresh ACL convergence."""
    columns = connection.execute("""
        SELECT column_name,privilege_type,is_grantable
        FROM information_schema.column_privileges
        WHERE table_schema='request_engine' AND table_name='native_identity_provision_receipts'
          AND grantee='request_platform_control_definer'
    """).fetchall()
    expected = {
        (column, privilege, "NO")
        for privilege, names in (
            (
                "SELECT",
                (
                    "actor_principal_id",
                    "idempotency_key_digest",
                    "intent_digest",
                    "native_identity_id",
                    "login_handle",
                ),
            ),
            (
                "INSERT",
                (
                    "actor_principal_id",
                    "idempotency_key_digest",
                    "intent_digest",
                    "native_identity_id",
                    "login_handle",
                    "correlation_id",
                ),
            ),
        )
        for column in names
    }
    table_acl = connection.execute("""
        SELECT privilege_type FROM information_schema.role_table_grants
        WHERE table_schema='request_engine' AND table_name='native_identity_provision_receipts'
          AND grantee='request_platform_control_definer'
    """).fetchall()
    if set(columns) != expected or table_acl:
        raise RuntimeError("native provisioning receipt privilege convergence mismatch")


def _database_url(database: str) -> str:
    host = os.environ.get("PGHOST", "127.0.0.1")
    port = os.environ.get("PGPORT", "5432")
    user = os.environ.get("PGUSER", "request_engine")
    password = os.environ.get("PGPASSWORD", "")
    return (
        f"postgresql+psycopg://{quote_plus(user)}:{quote_plus(password)}"
        f"@{host}:{port}/{quote_plus(database)}"
    )


def _verify_cleanup_worker_privileges(connection: psycopg.Connection[Any]) -> None:
    """Closed extension role: two reviewed primitives, never table or business ACLs."""
    role = connection.execute("""
        SELECT rolcanlogin,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls,rolconfig
        FROM pg_roles WHERE rolname='request_proof_cleanup_worker'
    """).fetchone()
    if role != (False, False, False, False, False, False, None):
        raise RuntimeError("cleanup worker role attributes mismatch")
    acl = connection.execute("""
        SELECT 'schema',n.nspname,a.privilege_type,a.is_grantable
        FROM pg_namespace n CROSS JOIN LATERAL aclexplode(n.nspacl) a
        WHERE a.grantee='request_proof_cleanup_worker'::regrole
        UNION ALL
        SELECT 'function',p.proname,a.privilege_type,a.is_grantable
        FROM pg_proc p CROSS JOIN LATERAL aclexplode(p.proacl) a
        WHERE a.grantee='request_proof_cleanup_worker'::regrole
        UNION ALL
        SELECT 'table',c.relname,a.privilege_type,a.is_grantable
        FROM pg_class c CROSS JOIN LATERAL aclexplode(c.relacl) a
        WHERE a.grantee='request_proof_cleanup_worker'::regrole
        UNION ALL
        SELECT 'column',c.attname,a.privilege_type,a.is_grantable
        FROM pg_attribute c CROSS JOIN LATERAL aclexplode(c.attacl) a
        WHERE a.grantee='request_proof_cleanup_worker'::regrole
        UNION ALL
        SELECT 'database',d.datname,a.privilege_type,a.is_grantable
        FROM pg_database d CROSS JOIN LATERAL aclexplode(d.datacl) a
        WHERE a.grantee='request_proof_cleanup_worker'::regrole
        UNION ALL
        SELECT 'type',t.typname,a.privilege_type,a.is_grantable
        FROM pg_type t CROSS JOIN LATERAL aclexplode(t.typacl) a
        WHERE a.grantee='request_proof_cleanup_worker'::regrole
        UNION ALL
        SELECT 'default',d.defaclobjtype::text,a.privilege_type,a.is_grantable
        FROM pg_default_acl d CROSS JOIN LATERAL aclexplode(d.defaclacl) a
        WHERE a.grantee='request_proof_cleanup_worker'::regrole
        ORDER BY 1,2
    """).fetchall()
    if acl != [
        ("function", "claim_temporary_proof_cleanup", "EXECUTE", False),
        ("function", "finish_temporary_proof_cleanup", "EXECUTE", False),
        ("schema", "request_cmd", "USAGE", False),
    ]:
        raise RuntimeError("cleanup worker ACL convergence mismatch")


def _run_alembic(database: str, target: str) -> None:
    env = os.environ.copy()
    env["MIGRATION_DATABASE_URL"] = _database_url(database)
    subprocess.run(
        ["uv", "run", "alembic", "upgrade", target],
        check=True,
        env=env,
    )


def _conninfo(database: str) -> str:
    return make_conninfo(
        host=os.environ.get("PGHOST", "127.0.0.1"),
        port=os.environ.get("PGPORT", "5432"),
        dbname=database,
        user=os.environ.get("PGUSER", "request_engine"),
        password=os.environ.get("PGPASSWORD", ""),
        connect_timeout=5,
        application_name="request-engine-multidatabase-proof",
    )


def main() -> None:
    source_database = os.environ.get("PGDATABASE", "request_engine_current")
    proof_database = f"re_multidb_proof_{uuid4().hex}"
    admin_conninfo = _conninfo("postgres")

    # The source database has already reached current HEAD when this proof runs.
    # Its baseline also created the Request Engine roles, which are cluster-global.
    with psycopg.connect(_conninfo(source_database)) as source:
        source_row = source.execute("SELECT version_num FROM alembic_version").fetchone()
        _verify_native_receipt_privileges(source)
        _verify_cleanup_worker_privileges(source)
    if source_row is None:
        raise RuntimeError("source database has no Alembic head")
    expected_head = str(source_row[0])

    with psycopg.connect(admin_conninfo, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(proof_database)))

    try:
        # A second clean database in the same PostgreSQL cluster must install
        # current HEAD while safely reusing the exact audited cluster-global
        # roles that the first database already created.
        _run_alembic(proof_database, "head")

        with psycopg.connect(_conninfo(proof_database)) as proof:
            _verify_native_receipt_privileges(proof)
            _verify_cleanup_worker_privileges(proof)
            head = proof.execute("SELECT version_num FROM alembic_version").fetchone()
            if head is None or str(head[0]) != expected_head:
                raise RuntimeError(
                    "second database did not reach the same Alembic head: "
                    f"source={expected_head!r} second={head!r}"
                )

            owners = proof.execute(
                """
                SELECT p.proname, pg_get_userbyid(p.proowner)
                  FROM pg_proc AS p
                  JOIN pg_namespace AS n ON n.oid = p.pronamespace
                 WHERE n.nspname = 'request_platform'
                   AND p.proname IN (
                       'read_principal_authority',
                       'establish_root',
                       'provision_tenant_provisioner'
                   )
                 ORDER BY p.proname
                """
            ).fetchall()
            expected_owners = [
                ("establish_root", "request_bootstrap_definer"),
                ("provision_tenant_provisioner", "request_platform_control_definer"),
                ("read_principal_authority", "request_platform_definer"),
            ]
            if owners != expected_owners:
                raise RuntimeError(f"second database definer ownership mismatch: {owners!r}")

            roles = proof.execute(
                """
                SELECT rolname, rolcanlogin, rolsuper, rolbypassrls
                  FROM pg_roles
                 WHERE rolname IN (
                     'request_bootstrap_definer',
                     'request_engine_admin',
                     'request_engine_app',
                     'request_engine_discovery',
                     'request_engine_discovery_definer',
                     'request_engine_schema_owner',
                     'request_engine_worker',
                     'request_platform_control',
                     'request_platform_control_definer',
                     'request_platform_definer',
                     'request_retention_recorder'
                 )
                 ORDER BY rolname
                """
            ).fetchall()
            expected_roles = [
                ("request_bootstrap_definer", False, False, True),
                ("request_engine_admin", False, False, True),
                ("request_engine_app", False, False, False),
                ("request_engine_discovery", False, False, False),
                ("request_engine_discovery_definer", False, False, True),
                ("request_engine_schema_owner", False, False, False),
                ("request_engine_worker", False, False, False),
                ("request_platform_control", False, False, False),
                ("request_platform_control_definer", False, False, True),
                ("request_platform_definer", False, False, True),
                ("request_retention_recorder", False, False, False),
            ]
            if roles != expected_roles:
                raise RuntimeError(f"second database managed role topology mismatch: {roles!r}")
            recorder_acl = proof.execute(
                """
                SELECT 'schema',n.nspname,a.privilege_type,a.is_grantable
                FROM pg_namespace n CROSS JOIN LATERAL aclexplode(n.nspacl) a
                WHERE a.grantee='request_retention_recorder'::regrole
                UNION ALL
                SELECT 'function',p.proname,a.privilege_type,a.is_grantable
                FROM pg_proc p CROSS JOIN LATERAL aclexplode(p.proacl) a
                WHERE a.grantee='request_retention_recorder'::regrole
                ORDER BY 1,2
                """
            ).fetchall()
            if recorder_acl != [
                ("function", "record_temporary_proof_retention", "EXECUTE", False),
                ("schema", "request_cmd", "USAGE", False),
            ]:
                raise RuntimeError(
                    f"second database retention recorder ACL mismatch: {recorder_acl!r}"
                )
            if proof.execute(
                "SELECT EXISTS(SELECT 1 FROM pg_roles "
                "WHERE rolname='request_engine_retention_recorder')"
            ).fetchone() != (False,):
                raise RuntimeError("second database left the legacy retention group behind")
    finally:
        with psycopg.connect(admin_conninfo, autocommit=True) as admin:
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(proof_database)
                )
            )

    print(
        "[PASS] second Request Engine database reached "
        f"{expected_head} alongside {source_database} using shared audited roles"
    )


if __name__ == "__main__":
    main()
