from __future__ import annotations

import os
import subprocess
from urllib.parse import quote_plus
from uuid import uuid4

import psycopg
from psycopg import sql


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


def main() -> None:
    source_database = os.environ.get("PGDATABASE", "request_engine_v3")
    proof_database = f"re_multidb_proof_{uuid4().hex}"
    admin_conninfo = psycopg.conninfo.make_conninfo(
        host=os.environ.get("PGHOST", "127.0.0.1"),
        port=os.environ.get("PGPORT", "5432"),
        dbname="postgres",
        user=os.environ.get("PGUSER", "request_engine"),
        password=os.environ.get("PGPASSWORD", ""),
        connect_timeout=5,
        application_name="request-engine-multidatabase-proof",
    )

    with psycopg.connect(admin_conninfo, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(proof_database)))

    try:
        # 0001 must remain installable after post-baseline cluster-global roles exist.
        _run_alembic(proof_database, "0001_initial")
        # The same database must then reach current HEAD while reusing exact
        # cluster-global control-plane roles rather than duplicating them unsafely.
        _run_alembic(proof_database, "head")

        with psycopg.connect(
            psycopg.conninfo.make_conninfo(
                host=os.environ.get("PGHOST", "127.0.0.1"),
                port=os.environ.get("PGPORT", "5432"),
                dbname=proof_database,
                user=os.environ.get("PGUSER", "request_engine"),
                password=os.environ.get("PGPASSWORD", ""),
            )
        ) as proof:
            head = proof.execute("SELECT version_num FROM alembic_version").fetchone()
            if head is None:
                raise RuntimeError("second database has no Alembic head")
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
            expected = [
                ("establish_root", "request_bootstrap_definer"),
                ("provision_tenant_provisioner", "request_platform_control_definer"),
                ("read_principal_authority", "request_platform_definer"),
            ]
            if owners != expected:
                raise RuntimeError(f"second database definer ownership mismatch: {owners!r}")

            roles = proof.execute(
                """
                SELECT rolname, rolcanlogin, rolsuper, rolbypassrls
                  FROM pg_roles
                 WHERE rolname IN (
                     'request_engine_platform_control',
                     'request_platform_control_definer'
                 )
                 ORDER BY rolname
                """
            ).fetchall()
            if roles != [
                ("request_engine_platform_control", False, False, False),
                ("request_platform_control_definer", False, False, True),
            ]:
                raise RuntimeError(f"second database platform role topology mismatch: {roles!r}")
    finally:
        with psycopg.connect(admin_conninfo, autocommit=True) as admin:
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(proof_database)
                )
            )

    print(f"[PASS] second Request Engine database migrated alongside {source_database}")


if __name__ == "__main__":
    main()
