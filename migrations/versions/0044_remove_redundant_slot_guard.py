"""Remove the redundant SlotOffer subject-only guard.

Revision ID: 0044_remove_redundant_slot_guard
Revises: 0043_queue_delivery_boundary
Create Date: 2026-09-05
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0044_remove_redundant_slot_guard"
down_revision: str | Sequence[str] | None = "0043_queue_delivery_boundary"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET ROLE request_engine_schema_owner")
    op.execute(
        "DROP TRIGGER slot_offers_00_guard_subject_match "
        "ON request_engine.slot_offers"
    )
    op.execute("DROP FUNCTION request_engine.guard_slot_offer_subject_match()")
    op.execute("RESET ROLE")


def downgrade() -> None:
    raise RuntimeError("SlotOffer guard consolidation is not reversible")
