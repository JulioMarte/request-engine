"""Add bounded F5 fallback sweep discovery.

Revision ID: 0018_f5_recovery_sweep_discovery
Revises: 0017_f5_escalation_policy
Create Date: 2026-08-29
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0018_f5_recovery_sweep_discovery"
down_revision: str | Sequence[str] | None = "0017_f5_escalation_policy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SQL = r"""
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, request_cmd, pg_catalog;

CREATE INDEX scheduled_actions_recovery_scope_idx
  ON request_engine.scheduled_actions (organization_id, action_type, subject_id)
  WHERE owner_module = 'operational_recovery';

CREATE OR REPLACE FUNCTION request_cmd.find_recovery_sweep_scopes(
    p_limit integer
) RETURNS TABLE (organization_id uuid, service_queue_id uuid)
LANGUAGE sql
SECURITY DEFINER
SET search_path = request_engine, pg_catalog
AS $function$
    SELECT DISTINCT
        sa.organization_id AS organization_id,
        sa.subject_id AS service_queue_id
    FROM request_engine.scheduled_actions sa
    WHERE sa.owner_module = 'operational_recovery'
      AND sa.action_type = 'reassess_recovery_scope'
      AND sa.subject_id IS NOT NULL
    ORDER BY 1, 2
    LIMIT GREATEST(LEAST(COALESCE(p_limit, 0), 500), 0)
$function$;
REVOKE ALL ON FUNCTION request_cmd.find_recovery_sweep_scopes(integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION request_cmd.find_recovery_sweep_scopes(integer)
  TO request_engine_worker, request_engine_admin;

RESET ROLE;
RESET search_path;
"""


def upgrade() -> None:
    op.execute(_SQL)


def downgrade() -> None:
    raise RuntimeError(
        "0018 introduces the F5 fallback sweep discovery surface and is not reversible"
    )
