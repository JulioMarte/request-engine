"""S3 delivery escalation lineage, live-lineage backstop and escalation ledger.

Revision ID: 0026_s3_escalation_lineage
Revises: 0025_s0b2_authority_and_history
Create Date: 2026-09-01
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0026_s3_escalation_lineage"
down_revision: str | Sequence[str] | None = "0025_s0b2_authority_and_history"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SQL = r"""
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, request_read, request_cmd, pg_catalog;

-- docs/v3/36 section 4: escalation links channel attempts into a notification
-- lineage. An escalated task carries parent_task_id, lineage_id (root) and its
-- escalation ordinal; a root task carries none of them.
ALTER TABLE request_engine.communication_tasks
  ADD COLUMN parent_task_id uuid;
ALTER TABLE request_engine.communication_tasks
  ADD COLUMN lineage_id uuid;
ALTER TABLE request_engine.communication_tasks
  ADD COLUMN escalation_ordinal integer
  CHECK (escalation_ordinal IS NULL OR escalation_ordinal >= 1);
ALTER TABLE request_engine.communication_tasks
  ADD CONSTRAINT communication_tasks_lineage_shape_check
  CHECK (
    (parent_task_id IS NULL AND lineage_id IS NULL AND escalation_ordinal IS NULL)
    OR (parent_task_id IS NOT NULL AND lineage_id IS NOT NULL
        AND escalation_ordinal IS NOT NULL)
  );
ALTER TABLE request_engine.communication_tasks
  ADD CONSTRAINT communication_tasks_parent_task_fk
  FOREIGN KEY (organization_id, parent_task_id)
  REFERENCES request_engine.communication_tasks (organization_id, id);

-- docs/v3/36 section 4: escalation is sequential, never parallel — at most one
-- live channel task per notification lineage.
CREATE UNIQUE INDEX communication_tasks_live_lineage_uq
  ON request_engine.communication_tasks (organization_id, lineage_id)
  WHERE lineage_id IS NOT NULL AND status IN ('pending', 'delivering');

-- docs/v3/36 section 4: escalation decisions are audited in an append-only
-- ledger; UPDATE and DELETE are rejected for every role including the owner.
CREATE TABLE request_engine.communication_escalations (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL REFERENCES request_engine.organizations(id),
    parent_task_id uuid NOT NULL,
    child_task_id uuid NOT NULL,
    trigger text NOT NULL CHECK (trigger IN (
        'delivery_deadline_missed', 'definitive_failure', 'recipient_unreachable')),
    from_channel text NOT NULL,
    to_channel text NOT NULL,
    ordinal integer NOT NULL CHECK (ordinal >= 1),
    failure_class text,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, parent_task_id, to_channel, ordinal),
    FOREIGN KEY (organization_id, parent_task_id)
        REFERENCES request_engine.communication_tasks (organization_id, id),
    FOREIGN KEY (organization_id, child_task_id)
        REFERENCES request_engine.communication_tasks (organization_id, id)
);

CREATE FUNCTION request_engine.guard_communication_escalations()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    RAISE EXCEPTION 'communication escalations is an append-only ledger'
        USING ERRCODE = '23514';
END
$function$;
CREATE TRIGGER communication_escalations_guard_append_only
BEFORE UPDATE OR DELETE ON request_engine.communication_escalations
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_communication_escalations();

REVOKE EXECUTE ON FUNCTION
  request_engine.guard_communication_escalations() FROM PUBLIC;

ALTER TABLE request_engine.communication_escalations
  ENABLE ROW LEVEL SECURITY;
ALTER TABLE request_engine.communication_escalations
  FORCE ROW LEVEL SECURITY;
CREATE POLICY communication_escalations_tenant_policy
  ON request_engine.communication_escalations
  USING (organization_id = request_engine.current_organization_id())
  WITH CHECK (organization_id = request_engine.current_organization_id());

REVOKE ALL ON request_engine.communication_escalations FROM PUBLIC;
REVOKE UPDATE ON request_engine.communication_escalations
  FROM request_engine_app;
GRANT SELECT, INSERT
  ON request_engine.communication_escalations TO request_engine_app;
GRANT ALL PRIVILEGES
  ON request_engine.communication_escalations TO request_engine_admin;

RESET ROLE;
RESET search_path;
"""


def upgrade() -> None:
    op.execute(_SQL)


def downgrade() -> None:
    raise RuntimeError("0026 introduces escalation lineage and is not reversible")
