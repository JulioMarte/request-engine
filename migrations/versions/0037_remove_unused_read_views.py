"""Remove unsupported read views with no current consumer.

Revision ID: 0037_remove_unused_read_views
Revises: 0036_append_only_lock_roots
Create Date: 2026-09-04
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0037_remove_unused_read_views"
down_revision: str | Sequence[str] | None = "0036_append_only_lock_roots"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UNUSED_READ_VIEWS = (
    "request_read.offering_summary_v1",
    "request_read.request_status_v1",
    "request_read.waitlist_status_v1",
)


def upgrade() -> None:
    op.execute("SET ROLE request_engine_schema_owner")
    for view in _UNUSED_READ_VIEWS:
        op.execute(f"DROP VIEW {view}")
    op.execute("RESET ROLE")


def downgrade() -> None:
    raise RuntimeError("removal of unsupported read views is not reversible")
