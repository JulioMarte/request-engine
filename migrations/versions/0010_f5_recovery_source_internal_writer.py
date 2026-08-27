"""Allow the F5 internal freshness writer through forced RLS.

Revision ID: 0010_f5_source_writer
Revises: 0009_f5_source_freshness
Create Date: 2026-08-27
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010_f5_source_writer"
down_revision: str | Sequence[str] | None = "0009_f5_source_freshness"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SQL = r"""
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, pg_catalog;

CREATE POLICY recovery_source_revisions_internal_writer_policy
  ON request_engine.recovery_source_revisions
  FOR ALL
  TO request_engine_schema_owner
  USING (true)
  WITH CHECK (true);

RESET ROLE;
RESET search_path;
"""


def upgrade() -> None:
    op.execute(_SQL)


def downgrade() -> None:
    raise RuntimeError("0010 is a security correction and is not reversible in place")
