from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, cast

_ROLE_NAMES = (
    "request_engine_admin",
    "request_engine_app",
    "request_engine_discovery",
    "request_engine_discovery_definer",
    "request_engine_schema_owner",
    "request_engine_worker",
)
_BYPASS_RLS = {
    "request_engine_admin",
    "request_engine_discovery_definer",
}


def _expected_role(name: str) -> dict[str, object]:
    return {
        "role_name": name,
        "superuser": False,
        "inherit": True,
        "create_role": False,
        "create_db": False,
        "can_login": False,
        "replication": False,
        "bypass_rls": name in _BYPASS_RLS,
        "connection_limit": -1,
        "valid_until": None,
        "has_password": False,
    }


def _load(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def validate(catalog: dict[str, Any]) -> list[dict[str, object]]:
    expected = [_expected_role(name) for name in _ROLE_NAMES]
    roles = catalog.get("roles")
    if roles != expected:
        raise ValueError(
            "Request Engine role attributes differ from the audited bootstrap contract"
        )
    if catalog.get("role_memberships") != []:
        raise ValueError("Request Engine role memberships must remain empty")
    if catalog.get("role_settings") != []:
        raise ValueError("Request Engine role settings require explicit bootstrap design")
    return expected


def render(catalog: dict[str, Any]) -> str:
    roles = validate(catalog)
    statements: list[str] = []
    for role in roles:
        name = str(role["role_name"]).replace('"', '""')
        bypass = "BYPASSRLS" if role["bypass_rls"] else "NOBYPASSRLS"
        statements.append(
            f'CREATE ROLE "{name}" WITH NOSUPERUSER INHERIT NOCREATEROLE '
            f"NOCREATEDB NOLOGIN NOREPLICATION {bypass} CONNECTION LIMIT -1;"
        )
    return "\n".join(statements) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render the audited Request Engine role bootstrap SQL"
    )
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    sql = render(_load(args.catalog))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(sql, encoding="utf-8")


if __name__ == "__main__":
    main()
