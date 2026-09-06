"""Restore intended column-scoped runtime update authority.

Revision ID: 0046_column_update_acl
Revises: 0045_global_taxonomy_acl
Create Date: 2026-09-05
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0046_column_update_acl"
down_revision: str | Sequence[str] | None = "0045_global_taxonomy_acl"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_COLUMN_UPDATE_AUTHORITY = {
    "operational_recovery_executions": (
        "communication_task_id",
        "completed_at",
        "failure_code",
        "resulting_reservation_revision",
        "status",
    ),
    "queue_entry_recall_holds": ("release_kind", "released_at"),
    "queue_entry_skips": ("consumed_at", "consumed_by_entry_id"),
}


def upgrade() -> None:
    op.execute("SET ROLE request_engine_schema_owner")
    for table, columns in _COLUMN_UPDATE_AUTHORITY.items():
        op.execute(f"REVOKE UPDATE ON request_engine.{table} FROM request_engine_app")
        column_list = ", ".join(columns)
        op.execute(f"GRANT UPDATE ({column_list}) ON request_engine.{table} TO request_engine_app")
    op.execute("RESET ROLE")


def downgrade() -> None:
    raise RuntimeError("column-scoped runtime authority hardening is not reversible")
