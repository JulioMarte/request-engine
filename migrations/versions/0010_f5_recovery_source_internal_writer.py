"""Allow only trigger-driven F5 freshness writes through forced RLS.

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

-- FORCE RLS also applies to SECURITY DEFINER functions owned by the schema
-- owner.  The internal writer therefore cannot use an unconditional owner
-- policy: doing so would also let request_read/request_cmd SECURITY DEFINER
-- functions read or lock another tenant's revision row.  Freshness bumps are
-- only required while one of the owner-controlled source-table triggers is
-- actively executing, so pg_trigger_depth() gives the writer the narrow
-- privilege it needs without widening ordinary owner execution.
CREATE POLICY recovery_source_revisions_internal_writer_policy
  ON request_engine.recovery_source_revisions
  FOR ALL
  TO request_engine_schema_owner
  USING (pg_trigger_depth() > 0)
  WITH CHECK (pg_trigger_depth() > 0);

RESET ROLE;
RESET search_path;
"""


def upgrade() -> None:
    op.execute(_SQL)


def downgrade() -> None:
    raise RuntimeError("0010 is a security correction and is not reversible in place")
