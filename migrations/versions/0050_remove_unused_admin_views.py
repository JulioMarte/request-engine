"""Remove unused pre-launch administrative worker views.

Revision ID: 0050_remove_unused_admin_views
Revises: 0049_consolidate_recovery_bump
Create Date: 2026-09-06
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0050_remove_unused_admin_views"
down_revision: str | Sequence[str] | None = "0049_consolidate_recovery_bump"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET ROLE request_engine_schema_owner")
    op.execute("DROP VIEW request_admin.outbox_health_v1")
    op.execute("DROP VIEW request_admin.scheduled_action_health_v1")
    op.execute("DROP VIEW request_admin.worker_dead_letters_v1")
    op.execute("RESET ROLE")


def downgrade() -> None:
    raise RuntimeError("pre-launch unused administrative view removal is not reversible")
