"""Request Engine V3 production baseline.

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-19
"""

import runpy
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import cast

from alembic import op

revision: str = "0001_initial"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PAYLOAD_LOADER = Path(__file__).resolve().parents[1] / "v3_initial_payload.py"


def _load_v3_initial_sql() -> str:
    namespace = runpy.run_path(str(_PAYLOAD_LOADER))
    loader = cast(Callable[[], str], namespace["load_v3_initial_sql"])
    return loader()


def upgrade() -> None:
    context = op.get_context()
    if context.as_sql:
        raise RuntimeError("V3 0001_initial requires Alembic online mode")
    bind = op.get_bind()
    if bind is None:
        raise RuntimeError("V3 0001_initial requires a live database connection")
    bind.exec_driver_sql(_load_v3_initial_sql())
    # The pg_dump-derived payload intentionally pins session settings while
    # replaying DDL. Restore defaults before Alembic records the revision.
    bind.exec_driver_sql("RESET ALL")


def downgrade() -> None:
    raise RuntimeError("V3 0001_initial is an irreversible production baseline")
