"""Add explicit provenance for automatic F5 recovery proposals.

Revision ID: 0014_f5_auto_proposals
Revises: 0013_f5_scheduled_reassessment
Create Date: 2026-08-28
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0014_f5_auto_proposals"
down_revision: str | Sequence[str] | None = "0013_f5_scheduled_reassessment"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SQL = r"""
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, pg_catalog;

ALTER TABLE request_engine.operational_recovery_proposals
  ALTER COLUMN created_by_principal_id DROP NOT NULL,
  ADD COLUMN creation_kind text NOT NULL DEFAULT 'operator',
  ADD COLUMN source_revision bigint;

ALTER TABLE request_engine.operational_recovery_proposals
  ADD CONSTRAINT operational_recovery_proposal_creation_kind_ck
  CHECK (creation_kind IN ('operator', 'automatic')),
  ADD CONSTRAINT operational_recovery_proposal_source_revision_ck
  CHECK (source_revision IS NULL OR source_revision > 0),
  ADD CONSTRAINT operational_recovery_proposal_actor_ck
  CHECK (
    (creation_kind = 'operator'
      AND created_by_principal_id IS NOT NULL
      AND source_revision IS NULL)
    OR
    (creation_kind = 'automatic'
      AND created_by_principal_id IS NULL
      AND source_revision IS NOT NULL)
  );

CREATE UNIQUE INDEX operational_recovery_auto_proposal_revision_uq
  ON request_engine.operational_recovery_proposals (
    organization_id, service_queue_id, source_revision
  )
  WHERE creation_kind = 'automatic';

RESET ROLE;
RESET search_path;
"""


def upgrade() -> None:
    op.execute(_SQL)


def downgrade() -> None:
    raise RuntimeError("0014 adds F5 automatic proposal provenance and is not reversible in place")
