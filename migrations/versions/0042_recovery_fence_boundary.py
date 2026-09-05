"""Make the recovery freshness ledger definer-mediated for the app role.

Revision ID: 0042_recovery_fence_boundary
Revises: 0041_reservation_window_index
Create Date: 2026-09-05
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0042_recovery_fence_boundary"
down_revision: str | Sequence[str] | None = "0041_reservation_window_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET ROLE request_engine_schema_owner")
    op.execute(
        "REVOKE SELECT, INSERT, UPDATE ON request_engine.recovery_source_revisions "
        "FROM request_engine_app"
    )
    op.execute("RESET ROLE")


def downgrade() -> None:
    raise RuntimeError("recovery freshness-fence boundary hardening is not reversible")
