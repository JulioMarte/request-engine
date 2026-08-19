"""Request Engine V3 production baseline.

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-19
"""

from collections.abc import Sequence

from alembic import op

from migrations.v3_initial_payload import load_v3_initial_sql

revision: str = "0001_initial"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    context = op.get_context()
    if context.as_sql:
        raise RuntimeError("V3 0001_initial requires Alembic online mode")
    bind = op.get_bind()
    if bind is None:
        raise RuntimeError("V3 0001_initial requires a live database connection")
    bind.exec_driver_sql(load_v3_initial_sql())


def downgrade() -> None:
    raise RuntimeError("V3 0001_initial is an irreversible production baseline")
