"""Remove unsupported administrative health views.

Revision ID: 0050_remove_admin_health_views
Revises: 0049_consolidate_recovery_bump
Create Date: 2026-09-06
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0050_remove_admin_health_views"
down_revision: str | Sequence[str] | None = "0049_consolidate_recovery_bump"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UNSUPPORTED_ADMIN_VIEWS = (
    "request_admin.outbox_health_v1",
    "request_admin.scheduled_action_health_v1",
)


def upgrade() -> None:
    op.execute("SET ROLE request_engine_schema_owner")
    for view in _UNSUPPORTED_ADMIN_VIEWS:
        op.execute(f"DROP VIEW {view}")
    op.execute("RESET ROLE")


def downgrade() -> None:
    raise RuntimeError("pre-launch unsupported admin health view removal is not reversible")
