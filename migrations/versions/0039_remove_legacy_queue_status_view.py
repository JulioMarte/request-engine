"""Remove the legacy queue-status read projection.

Revision ID: 0039_remove_queue_status_v1
Revises: 0038_future_acl_fail_closed
Create Date: 2026-09-04
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0039_remove_queue_status_v1"
down_revision: str | Sequence[str] | None = "0038_future_acl_fail_closed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET ROLE request_engine_schema_owner")
    op.execute("DROP VIEW request_read.service_queue_status_v1")
    op.execute("RESET ROLE")


def downgrade() -> None:
    raise RuntimeError("removal of legacy queue-status view is not reversible")
