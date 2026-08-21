#!/usr/bin/env python3
"""Mechanically consolidate the unshipped F1 Alembic revisions into 0002."""

from __future__ import annotations

import ast
from pathlib import Path

# One-shot development utility. Delete after the generated revision is validated.
ROOT = Path(__file__).resolve().parents[2]
VERSIONS = ROOT / "migrations" / "versions"
PARTS = (
    VERSIONS / "0002_operational_profile_contextual_supply.py",
    VERSIONS / "0003_f1_commercial_context_sources.py",
    VERSIONS / "0004_f1_shared_capacity_guard_compat.py",
    VERSIONS / "0005_f1_runtime_privilege_hardening.py",
)
RUNNER = ROOT / "scripts" / "ci" / "run_f1_operational_profile.sh"


def _upgrade_sql(path: Path) -> str:
    module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in module.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "_UPGRADE_SQL" for target in node.targets):
            continue
        value = ast.literal_eval(node.value)
        if not isinstance(value, str):
            raise TypeError(f"{path}: _UPGRADE_SQL is not a string")
        return value
    raise ValueError(f"{path}: _UPGRADE_SQL not found")


def _literal(value: str) -> str:
    delimiter = 'r"""'
    if '"""' in value:
        raise ValueError("unexpected triple quote in migration SQL")
    return f'{delimiter}{value}"""'


def main() -> None:
    sql_parts = tuple(_upgrade_sql(path) for path in PARTS)
    generated = f'''\"\"\"Add F1 operational profile and contextual supply.\n\nRevision ID: 0002_f1_supply\nRevises: 0001_initial\nCreate Date: 2026-08-20\n\nThis is the greenfield launch revision for F1. The feature had not been\ndeployed and no production/customer data existed when its provisional\n0002-0005 development revisions were consolidated.\n\"\"\"\n\nfrom collections.abc import Sequence\n\nfrom alembic import op\nfrom psycopg import ClientCursor, sql\n\nrevision: str = \"0002_f1_supply\"\ndown_revision: str | Sequence[str] | None = \"0001_initial\"\nbranch_labels: str | Sequence[str] | None = None\ndepends_on: str | Sequence[str] | None = None\n\n\n_BASE_SQL = {_literal(sql_parts[0])}\n\n_COMMERCIAL_PROVENANCE_SQL = {_literal(sql_parts[1])}\n\n_SHARED_CAPACITY_GUARD_SQL = {_literal(sql_parts[2])}\n\n_RUNTIME_ACL_SQL = {_literal(sql_parts[3])}\n\n\ndef upgrade() -> None:\n    context = op.get_context()\n    if context.as_sql:\n        raise RuntimeError(\"F1 migration requires Alembic online mode\")\n    bind = op.get_bind()\n    if bind is None:\n        raise RuntimeError(\"F1 migration requires a live database connection\")\n    driver_connection = bind.connection.driver_connection\n    if driver_connection is None:\n        raise RuntimeError(\"F1 migration requires the live psycopg driver connection\")\n    with ClientCursor(driver_connection) as cursor:\n        cursor.execute(sql.SQL(_BASE_SQL))\n    bind.exec_driver_sql(\"RESET ALL\")\n    op.execute(_COMMERCIAL_PROVENANCE_SQL)\n    op.execute(_SHARED_CAPACITY_GUARD_SQL)\n    op.execute(_RUNTIME_ACL_SQL)\n\n\ndef downgrade() -> None:\n    raise RuntimeError(\n        \"0002_f1_supply contains F1 configuration and commercial provenance \"\n        \"and is intentionally irreversible\"\n    )\n'''
    PARTS[0].write_text(generated, encoding="utf-8", newline="\n")
    for path in PARTS[1:]:
        path.unlink()

    runner = RUNNER.read_text(encoding="utf-8")
    old = 'EXPECTED_HEAD="0005_f1_runtime_acl"'
    new = 'EXPECTED_HEAD="0002_f1_supply"'
    if old not in runner:
        raise ValueError("F1 CI runner no longer has the expected provisional Alembic head")
    RUNNER.write_text(runner.replace(old, new), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
