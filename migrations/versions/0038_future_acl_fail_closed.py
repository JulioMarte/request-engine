"""Make future application relation authority fail closed.

Revision ID: 0038_future_acl_fail_closed
Revises: 0037_remove_unused_read_views
Create Date: 2026-09-04
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0038_future_acl_fail_closed"
down_revision: str | Sequence[str] | None = "0037_remove_unused_read_views"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET ROLE request_engine_schema_owner")
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA request_engine "
        "REVOKE SELECT, INSERT, UPDATE ON TABLES FROM request_engine_app"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA request_read "
        "REVOKE SELECT ON TABLES FROM request_engine_app"
    )
    op.execute("RESET ROLE")


def downgrade() -> None:
    raise RuntimeError("future relation ACL hardening is not reversible")
