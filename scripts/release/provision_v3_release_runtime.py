#!/usr/bin/env python3
"""Provision ephemeral release-shaped runtime LOGINs for the G19 proof."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shlex
from pathlib import Path
from urllib.parse import quote_plus

import psycopg
from psycopg import sql

RUNTIME_ROLES = {
    "app": "request_engine_app",
    "worker": "request_engine_worker",
    "admin": "request_engine_admin",
}


def _connection() -> psycopg.Connection[tuple[object, ...]]:
    return psycopg.connect(
        host=os.environ.get("PGHOST", "127.0.0.1"),
        port=os.environ.get("PGPORT", "5432"),
        dbname=os.environ.get("PGDATABASE", "request_engine_v3"),
        user=os.environ.get("PGUSER", "postgres"),
        password=os.environ.get("PGPASSWORD", "postgres"),
        autocommit=True,
    )


def _role_record(
    conn: psycopg.Connection[tuple[object, ...]], role_name: str, parent_role: str
) -> dict[str, object]:
    row = conn.execute(
        """
        SELECT rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls
          FROM pg_roles
         WHERE rolname = %s
        """,
        (role_name,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"runtime role {role_name!r} was not created")
    memberships = [
        str(item[0])
        for item in conn.execute(
            """
            SELECT parent.rolname
              FROM pg_auth_members membership
              JOIN pg_roles child ON child.oid = membership.member
              JOIN pg_roles parent ON parent.oid = membership.roleid
             WHERE child.rolname = %s
             ORDER BY parent.rolname
            """,
            (role_name,),
        ).fetchall()
    ]
    expected_attributes = {
        "can_login": True,
        "superuser": False,
        "create_db": False,
        "create_role": False,
        "replication": False,
        "bypass_rls": False,
    }
    attributes = dict(zip(expected_attributes, (bool(value) for value in row), strict=True))
    return {
        "role_name": role_name,
        "parent_role": parent_role,
        "attributes": attributes,
        "memberships": memberships,
        "status": (
            "PASS"
            if attributes == expected_attributes and memberships == [parent_role]
            else "FAIL"
        ),
    }


def _database_url(role_name: str, password: str) -> str:
    host = os.environ.get("PGHOST", "127.0.0.1")
    port = os.environ.get("PGPORT", "5432")
    database = os.environ.get("PGDATABASE", "request_engine_v3")
    return (
        f"postgresql+asyncpg://{quote_plus(role_name)}:{quote_plus(password)}"
        f"@{host}:{port}/{database}"
    )


def provision(output: Path, env_output: Path) -> int:
    token = secrets.token_hex(6)
    credentials: dict[str, tuple[str, str]] = {}
    conn = _connection()
    try:
        for key, parent_role in RUNTIME_ROLES.items():
            role_name = f"re_g19_{key}_{token}"
            password = secrets.token_urlsafe(32)
            conn.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN INHERIT NOBYPASSRLS NOSUPERUSER "
                    "NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD {}"
                ).format(sql.Identifier(role_name), sql.Literal(password))
            )
            conn.execute(
                sql.SQL("GRANT {} TO {}").format(
                    sql.Identifier(parent_role), sql.Identifier(role_name)
                )
            )
            credentials[key] = (role_name, password)

        role_records = [
            _role_record(conn, credentials[key][0], parent_role)
            for key, parent_role in RUNTIME_ROLES.items()
        ]
        server_version = int(
            conn.execute("SHOW server_version_num").fetchone()[0]  # type: ignore[index]
        )
    finally:
        conn.close()

    env_values = {
        "REQUEST_ENGINE_APP_DATABASE_URL": _database_url(*credentials["app"]),
        "REQUEST_ENGINE_WORKER_DATABASE_URL": _database_url(*credentials["worker"]),
        "REQUEST_ENGINE_ADMIN_DATABASE_URL": _database_url(*credentials["admin"]),
        "REQUEST_ENGINE_APP_ROLE_NAME": credentials["app"][0],
        "REQUEST_ENGINE_WORKER_ROLE_NAME": credentials["worker"][0],
        "REQUEST_ENGINE_ADMIN_ROLE_NAME": credentials["admin"][0],
    }
    env_output.parent.mkdir(parents=True, exist_ok=True)
    env_output.write_text(
        "".join(f"export {key}={shlex.quote(value)}\n" for key, value in env_values.items()),
        encoding="utf-8",
    )
    env_output.chmod(0o600)

    status = "PASS" if server_version // 10000 == 18 and all(
        item["status"] == "PASS" for item in role_records
    ) else "FAIL"
    payload = {
        "proof": "v3-production-like-runtime-provisioning",
        "status": status,
        "postgresql_major": server_version // 10000,
        "database": os.environ.get("PGDATABASE", "request_engine_v3"),
        "runtime_roles": role_records,
        "secrets_redacted": True,
        "runtime_env_file": str(env_output),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return 0 if status == "PASS" else 1


def cleanup(proof_path: Path) -> int:
    if not proof_path.exists():
        return 0
    payload = json.loads(proof_path.read_text(encoding="utf-8"))
    roles = [item["role_name"] for item in payload.get("runtime_roles", [])]
    conn = _connection()
    try:
        for role_name in roles:
            conn.execute(
                sql.SQL("REASSIGN OWNED BY {} TO request_engine_schema_owner").format(
                    sql.Identifier(role_name)
                )
            )
            conn.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role_name)))
            conn.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role_name)))
    finally:
        conn.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".phase6/v3-production-like-runtime.json"),
    )
    parser.add_argument(
        "--env-output",
        type=Path,
        default=Path(".ci/v3-production-like-runtime.env"),
    )
    parser.add_argument("--cleanup", action="store_true")
    args = parser.parse_args()
    if args.cleanup:
        return cleanup(args.output)
    return provision(args.output, args.env_output)


if __name__ == "__main__":
    raise SystemExit(main())
