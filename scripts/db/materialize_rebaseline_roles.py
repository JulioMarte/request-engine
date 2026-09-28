from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _ident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _bool(value: bool, yes: str, no: str) -> str:
    return yes if value else no


def _role_statement(role: dict[str, Any]) -> str:
    if role.get("has_password"):
        raise SystemExit(
            f"refusing to materialize credential-bearing role {role['role_name']!r} into baseline"
        )
    attrs = [
        _bool(role["superuser"], "SUPERUSER", "NOSUPERUSER"),
        _bool(role["inherit"], "INHERIT", "NOINHERIT"),
        _bool(role["create_role"], "CREATEROLE", "NOCREATEROLE"),
        _bool(role["create_db"], "CREATEDB", "NOCREATEDB"),
        _bool(role["can_login"], "LOGIN", "NOLOGIN"),
        _bool(role["replication"], "REPLICATION", "NOREPLICATION"),
        _bool(role["bypass_rls"], "BYPASSRLS", "NOBYPASSRLS"),
        f"CONNECTION LIMIT {int(role['connection_limit'])}",
    ]
    if role.get("valid_until"):
        attrs.append(f"VALID UNTIL {_literal(role['valid_until'])}")
    return f"CREATE ROLE {_ident(role['role_name'])} WITH {' '.join(attrs)};"


def materialize(catalog: dict[str, Any]) -> str:
    lines = [
        "-- Generated from the audited Request Engine role catalog.",
        "-- Credentials are intentionally forbidden from this payload.",
        "",
    ]
    for role in catalog.get("roles", []):
        lines.append(_role_statement(role))

    memberships = catalog.get("role_memberships", [])
    if memberships:
        lines.append("")
        lines.append("-- Role memberships")
    for membership in memberships:
        if not membership.get("inherit_option", True) or not membership.get(
            "set_option", True
        ):
            raise SystemExit(
                "non-default PostgreSQL membership INHERIT/SET options require "
                "explicit review before rebaseline"
            )
        suffix = " WITH ADMIN OPTION" if membership.get("admin_option") else ""
        lines.append(
            "GRANT "
            f"{_ident(membership['parent_role'])} "
            f"TO {_ident(membership['member_role'])}{suffix};"
        )

    settings = catalog.get("role_settings", [])
    if settings:
        lines.append("")
        lines.append("-- Role settings")
    for setting in settings:
        role_name = _ident(setting["role_name"])
        database_name = setting.get("database_name") or ""
        prefix = f"ALTER ROLE {role_name}"
        if database_name:
            prefix += f" IN DATABASE {_ident(database_name)}"
        for item in setting.get("settings") or []:
            if "=" not in item:
                raise SystemExit(f"unexpected role setting format: {item!r}")
            key, value = item.split("=", 1)
            lines.append(f"{prefix} SET {_ident(key)} TO {_literal(value)};")

    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("catalog", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    rendered = materialize(catalog)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")


if __name__ == "__main__":
    main()
