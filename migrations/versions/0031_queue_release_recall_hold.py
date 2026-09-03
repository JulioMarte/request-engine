"""Admit operator release for same-day recall holds (S5a completion).

Revision ID: 0031_queue_release_recall_hold
Revises: 0030_s0d_federated_identity
Create Date: 2026-09-03
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0031_queue_release_recall_hold"
down_revision: str | Sequence[str] | None = "0030_s0d_federated_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SQL = r"""
SET ROLE request_engine_schema_owner;

ALTER TABLE request_engine.queue_entry_recall_holds
    DROP CONSTRAINT IF EXISTS queue_entry_recall_holds_release_kind_ck;
ALTER TABLE request_engine.queue_entry_recall_holds
    DROP CONSTRAINT IF EXISTS queue_entry_recall_holds_release_kind_check;
ALTER TABLE request_engine.queue_entry_recall_holds
    ADD CONSTRAINT queue_entry_recall_holds_release_kind_ck
    CHECK (release_kind IS NULL OR release_kind IN
      ('expired','operator_select','condition_satisfied','operator_release'));

RESET ROLE;
"""


def upgrade() -> None:
    op.execute(_SQL)


def downgrade() -> None:
    raise RuntimeError("0031 extends the authoritative triage release vocabulary")
