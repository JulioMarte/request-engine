"""Request Engine current-product PostgreSQL baseline.

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-06
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


def _load_baseline() -> tuple[Callable[[], str], Callable[[Any], None], Callable[[Any], None]]:
    namespace = runpy.run_path(str(_LOADER))
    load_schema = cast(Callable[[], str], namespace["load_schema_sql"])
    require_clean = cast(Callable[[Any], None], namespace["require_clean_database"])
    ensure_roles = cast(Callable[[Any], None], namespace["ensure_exact_roles"])
    return load_schema, require_clean, ensure_roles


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

    load_schema, require_clean, ensure_roles = _load_baseline()
    schema_sql = load_schema()
    require_clean(driver_connection)
    ensure_roles(driver_connection)

    # The reviewed schema is an exact pg_dump-derived multi-statement batch.
    # ClientCursor uses Psycopg's simple query protocol, so PostgreSQL receives
    # the audited SQL without parsing or statement rewriting in Python.
    with ClientCursor(driver_connection) as cursor:
        cursor.execute(sql.SQL(schema_sql))

    # The pg_dump-derived payload pins session settings while replaying DDL.
    # Restore defaults before Alembic records the revision.
    bind.exec_driver_sql("RESET ALL")


def downgrade() -> None:
    raise RuntimeError("0001_initial is an irreversible pre-production baseline")
