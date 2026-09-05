"""Remove direct app authority over global service classification taxonomy.

Revision ID: 0045_global_taxonomy_acl
Revises: 0044_remove_redundant_slot_guard
Create Date: 2026-09-05
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0045_global_taxonomy_acl"
down_revision: str | Sequence[str] | None = "0044_remove_redundant_slot_guard"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET ROLE request_engine_schema_owner")
    op.execute(
        "REVOKE INSERT, UPDATE ON request_engine.service_classifications "
        "FROM request_engine_app"
    )
    op.execute("RESET ROLE")


def downgrade() -> None:
    raise RuntimeError("global taxonomy authority hardening is not reversible")
