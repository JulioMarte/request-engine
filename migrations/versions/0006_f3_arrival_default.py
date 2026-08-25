"""Harden F3 arrival/admission defaults for legacy queue.join inserts.

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
    # Legacy queue.join omits both timestamps. Using one statement-stable database
    # clock makes immediate arrival and admission the same fact while preserving
    # database authority and deterministic FIFO tie-breaking by (admitted_at, id).
    op.execute(
        "ALTER TABLE request_engine.queue_entries "
        "ALTER COLUMN arrived_at SET DEFAULT statement_timestamp(), "
        "ALTER COLUMN admitted_at SET DEFAULT statement_timestamp()"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE request_engine.queue_entries "
        "ALTER COLUMN arrived_at SET DEFAULT clock_timestamp(), "
        "ALTER COLUMN admitted_at SET DEFAULT clock_timestamp()"
    )
