from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from psycopg import ClientCursor

ROOT = Path(__file__).resolve().parent
MANIFEST_PATH = ROOT / "manifest.json"
APPLICATION_SCHEMAS = ("request_admin", "request_cmd", "request_engine", "request_read")
_ROLE_NAME = re.compile(r'^CREATE ROLE "([^"]+)" WITH .+;$')
_ROLE_QUERY = """
    SELECT rolname,
           rolsuper,
           rolinherit,
           rolcreaterole,
           rolcreatedb,
           rolcanlogin,
           rolreplication,
           rolbypassrls,
           rolconnlimit,
           rolvaliduntil::text,
           rolpassword IS NOT NULL
    FROM pg_authid
    WHERE rolname LIKE 'request_engine_%'
    ORDER BY rolname
"""
_MEMBERSHIP_QUERY = """
    SELECT parent.rolname, member.rolname
    FROM pg_auth_members membership
    JOIN pg_roles parent ON parent.oid = membership.roleid
    JOIN pg_roles member ON member.oid = membership.member
    WHERE parent.rolname LIKE 'request_engine_%'
       OR member.rolname LIKE 'request_engine_%'
    ORDER BY parent.rolname, member.rolname
"""
_SETTING_QUERY = """
    SELECT role.rolname, COALESCE(database.datname, ''), setting.setconfig
    FROM pg_db_role_setting setting
    JOIN pg_roles role ON role.oid = setting.setrole
    LEFT JOIN pg_database database ON database.oid = setting.setdatabase
    WHERE role.rolname LIKE 'request_engine_%'
    ORDER BY role.rolname, database.datname
"""
_ROLE_FIELDS = (
    "superuser",
    "inherit",
    "create_role",
    "create_db",
    "can_login",
    "replication",
    "bypass_rls",
    "connection_limit",
    "valid_until",
    "has_password",
)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _manifest() -> dict[str, Any]:
    payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise RuntimeError("unsupported rebaseline candidate manifest")
    return payload


def _verified_file(path: Path, *, expected_bytes: int, expected_sha256: str) -> bytes:
    payload = path.read_bytes()
    if len(payload) != expected_bytes:
        raise RuntimeError(
            f"{path.name}: expected {expected_bytes} bytes, found {len(payload)}"
        )
    digest = _sha256(payload)
    if digest != expected_sha256:
        raise RuntimeError(
            f"{path.name}: expected sha256 {expected_sha256}, found {digest}"
        )
    return payload


def load_schema_sql() -> str:
    manifest = _manifest()["schema_payload"]
    payloads: list[bytes] = []
    for part in manifest["materialized_parts"]:
        payloads.append(
            _verified_file(
                ROOT / part["path"],
                expected_bytes=part["bytes"],
                expected_sha256=part["sha256"],
            )
        )
    payload = b"".join(payloads)
    if len(payload) != manifest["bytes"]:
        raise RuntimeError("materialized schema byte length does not match manifest")
    if _sha256(payload) != manifest["sha256"]:
        raise RuntimeError("materialized schema checksum does not match manifest")
    text = payload.decode("utf-8")
    if any(line.startswith("\\") for line in text.splitlines()):
        raise RuntimeError("rebaseline schema contains a psql meta-command")
    return text


def load_role_statements() -> dict[str, str]:
    role_manifest = _manifest()["role_bootstrap"]
    payload = _verified_file(
        ROOT / role_manifest["path"],
        expected_bytes=role_manifest["bytes"],
        expected_sha256=role_manifest["sha256"],
    )
    statements: dict[str, str] = {}
    for line in payload.decode("utf-8").splitlines():
        statement = line.strip()
        if not statement:
            continue
        match = _ROLE_NAME.fullmatch(statement)
        if match is None:
            raise RuntimeError("rebaseline role bootstrap contains an unexpected statement")
        role_name = match.group(1)
        if role_name in statements:
            raise RuntimeError(f"duplicate rebaseline role statement: {role_name}")
        statements[role_name] = statement

    expected_roles = role_manifest["expected_roles"]
    if set(statements) != set(expected_roles):
        raise RuntimeError("rebaseline role statements do not match manifest role names")
    if len(statements) != _manifest()["effective_model"]["roles"]:
        raise RuntimeError("rebaseline role bootstrap count does not match manifest")
    return statements


def _actual_roles(cursor: ClientCursor[Any]) -> dict[str, dict[str, Any]]:
    rows = cursor.execute(_ROLE_QUERY).fetchall()
    return {
        str(row[0]): dict(zip(_ROLE_FIELDS, row[1:], strict=True))
        for row in rows
    }


def require_clean_database(driver_connection: Any) -> None:
    with ClientCursor(driver_connection) as cursor:
        rows = cursor.execute(
            """
            SELECT nspname
            FROM pg_namespace
            WHERE nspname = ANY(%s)
            ORDER BY nspname
            """,
            (list(APPLICATION_SCHEMAS),),
        ).fetchall()
    if rows:
        names = ", ".join(str(row[0]) for row in rows)
        raise RuntimeError(
            "replacement 0001 requires a clean database; existing Request Engine schemas: "
            + names
        )


def ensure_exact_roles(driver_connection: Any) -> None:
    role_manifest = _manifest()["role_bootstrap"]
    expected_roles = role_manifest["expected_roles"]
    statements = load_role_statements()

    with ClientCursor(driver_connection) as cursor:
        actual = _actual_roles(cursor)
        unexpected = sorted(set(actual) - set(expected_roles))
        if unexpected:
            raise RuntimeError(
                "unexpected Request Engine roles already exist: " + ", ".join(unexpected)
            )

        for role_name in sorted(set(expected_roles) - set(actual)):
            cursor.execute(statements[role_name])

        actual = _actual_roles(cursor)
        if set(actual) != set(expected_roles):
            raise RuntimeError("Request Engine role bootstrap did not produce the expected role set")
        for role_name, expected in expected_roles.items():
            if actual[role_name] != expected:
                raise RuntimeError(
                    f"existing Request Engine role {role_name} does not match audited topology"
                )

        memberships = cursor.execute(_MEMBERSHIP_QUERY).fetchall()
        if memberships != role_manifest["role_memberships"]:
            raise RuntimeError("Request Engine roles have unexpected role memberships")

        settings = cursor.execute(_SETTING_QUERY).fetchall()
        if settings != role_manifest["role_settings"]:
            raise RuntimeError("Request Engine roles have unexpected role settings")
