"""Add a tenant-scoped temporal access path for Reservation window reads.

Revision ID: 0041_reservation_window_index
Revises: 0040_consolidate_revision_guard
Create Date: 2026-09-05
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0041_reservation_window_index"
down_revision: str | Sequence[str] | None = "0040_consolidate_revision_guard"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET ROLE request_engine_schema_owner")
    op.execute(
        "CREATE INDEX reservations_org_during_gist "
        "ON request_engine.reservations USING gist (organization_id, during)"
    )
    op.execute("RESET ROLE")


def downgrade() -> None:
    raise RuntimeError("reservation temporal-index hardening is not reversible")
