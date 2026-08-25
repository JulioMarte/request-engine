"""Harden F3 arrival default for legacy queue.join inserts.

Revision ID: 0006_f3_arrival_default
Revises: 0005_live_service_ops
Create Date: 2026-08-25
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006_f3_arrival_default"
down_revision: str | Sequence[str] | None = "0005_live_service_ops"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Existing queue.join relies on column defaults. statement_timestamp() is
    # guaranteed not to occur after admitted_at's later clock_timestamp() default,
    # preserving arrived_at <= admitted_at without rewriting the proven FIFO command.
    op.execute(
        "ALTER TABLE request_engine.queue_entries "
        "ALTER COLUMN arrived_at SET DEFAULT statement_timestamp()"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE request_engine.queue_entries "
        "ALTER COLUMN arrived_at SET DEFAULT clock_timestamp()"
    )
