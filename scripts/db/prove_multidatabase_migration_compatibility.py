from __future__ import annotations

import os
import subprocess
from urllib.parse import quote_plus
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo


def _database_url(database: str) -> str:
    host = os.environ.get("PGHOST", "127.0.0.1")
    port = os.environ.get("PGPORT", "5432")
    user = os.environ.get("PGUSER", "request_engine")
    password = os.environ.get("PGPASSWORD", "")
    return (
        f"postgresql+psycopg://{quote_plus(user)}:{quote_plus(password)}"
        f"@{host}:{port}/{quote_plus(database)}"
    )


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
                     'request_platform_definer'
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
            ]
            if roles != expected_roles:
                raise RuntimeError(f"second database managed role topology mismatch: {roles!r}")
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
