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


_TABLES = (
    "operational_recovery_executions",
    "queue_entry_recall_holds",
    "queue_entry_skips",
)


def upgrade() -> None:
    op.execute("SET ROLE request_engine_schema_owner")
    for table in _TABLES:
        op.execute(f"REVOKE UPDATE ON request_engine.{table} FROM request_engine_app")
    op.execute("RESET ROLE")


def downgrade() -> None:
    raise RuntimeError("column-scoped runtime authority hardening is not reversible")
