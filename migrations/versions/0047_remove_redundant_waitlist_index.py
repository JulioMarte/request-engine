"""Remove the redundant narrow waitlist selection index.

Revision ID: 0047_remove_waitlist_index
Revises: 0046_column_update_acl
Create Date: 2026-09-05
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0047_remove_waitlist_index"
down_revision: str | Sequence[str] | None = "0046_column_update_acl"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET ROLE request_engine_schema_owner")
    op.execute("DROP INDEX request_engine.waitlist_entries_selection_idx")
    op.execute("RESET ROLE")


def downgrade() -> None:
    raise RuntimeError("redundant waitlist index removal is not reversible")
