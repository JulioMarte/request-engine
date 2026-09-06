"""Remove pre-launch legacy Resource location and availability schema.

Revision ID: 0048_remove_legacy_location
Revises: 0047_remove_waitlist_index
Create Date: 2026-09-05
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0048_remove_legacy_location"
down_revision: str | Sequence[str] | None = "0047_remove_waitlist_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET ROLE request_engine_schema_owner")
    op.execute("DROP TABLE request_engine.availability_schedules")
    op.execute("ALTER TABLE request_engine.resources DROP COLUMN location_id")
    op.execute("RESET ROLE")


def downgrade() -> None:
    raise RuntimeError("pre-launch legacy Resource location removal is not reversible")
