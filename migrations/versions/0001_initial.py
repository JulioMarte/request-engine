"""Request Engine current-product PostgreSQL baseline.

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-23

Pre-production history collapse of the former 0001_initial + 0002..0047 chain
(see docs/audits/postgresql-rebaseline-0047.md). The payload in
migrations/baseline/ reproduces the effective PostgreSQL 18 model at historical
head 0047_reservation_calendar_read.
"""

import runpy
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, cast

from alembic import op
from psycopg import ClientCursor, sql

revision: str = "0001_initial"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LOADER = Path(__file__).resolve().parents[1] / "baseline" / "loader.py"


def _load_baseline() -> dict[str, Callable[..., Any]]:
    namespace = runpy.run_path(str(_LOADER))
    names = (
        "load_schema_sql",
        "load_extension_role_sql",
        "load_post_install_audit_sql",
        "require_clean_database",
        "ensure_exact_roles",
        "ensure_extension_roles",
        "run_post_install_audit",
    )
    return {name: cast(Callable[..., Any], namespace[name]) for name in names}


def upgrade() -> None:
    context = op.get_context()
    if context.as_sql:
        raise RuntimeError("0001_initial requires Alembic online mode")
    bind = op.get_bind()
    if bind is None:
        raise RuntimeError("0001_initial requires a live database connection")

    driver_connection = bind.connection.driver_connection
    if driver_connection is None:
        raise RuntimeError("0001_initial requires the live psycopg driver connection")

    baseline = _load_baseline()
    # Verify every checksummed payload before touching the cluster.
    schema_sql = cast(str, baseline["load_schema_sql"]())
    baseline["load_extension_role_sql"]()
    baseline["load_post_install_audit_sql"]()
    baseline["require_clean_database"](driver_connection)
    baseline["ensure_exact_roles"](driver_connection)
    baseline["ensure_extension_roles"](driver_connection)

    # The reviewed schema is an exact pg_dump-derived multi-statement batch.
    # ClientCursor uses Psycopg's simple query protocol, so PostgreSQL receives
    # the audited SQL without parsing or statement rewriting in Python.
    with ClientCursor(driver_connection) as cursor:
        cursor.execute(sql.SQL(schema_sql))

    # The pg_dump-derived payload pins session settings while replaying DDL.
    # Restore defaults before the post-install audit and Alembic bookkeeping.
    bind.exec_driver_sql("RESET ALL")
    baseline["run_post_install_audit"](driver_connection)


def downgrade() -> None:
    raise RuntimeError("0001_initial is an irreversible pre-production baseline")
