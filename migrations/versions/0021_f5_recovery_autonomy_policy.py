"""Add the operator-granted autonomous reschedule envelope.

Revision ID: 0021_recovery_autonomy_policy
Revises: 0020_public_execute_hardening
Create Date: 2026-08-30
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0021_recovery_autonomy_policy"
down_revision: str | Sequence[str] | None = "0020_public_execute_hardening"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SQL = r"""
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, request_read, request_cmd, pg_catalog;

CREATE TABLE request_engine.operational_recovery_autonomy_policies (
    organization_id uuid NOT NULL,
    service_queue_id uuid NOT NULL,
    enabled boolean NOT NULL,
    max_delay_minutes integer NOT NULL,
    max_auto_actions_per_incident integer NOT NULL,
    granted_by uuid NOT NULL,
    granted_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (organization_id, service_queue_id),
    FOREIGN KEY (organization_id, service_queue_id)
      REFERENCES request_engine.service_queues (organization_id, id),
    FOREIGN KEY (organization_id, granted_by)
      REFERENCES request_engine.principals (organization_id, id),
    CHECK (max_delay_minutes > 0),
    CHECK (max_auto_actions_per_incident > 0),
    CHECK (granted_at <= updated_at)
);

ALTER TABLE request_engine.operational_recovery_autonomy_policies
  ENABLE ROW LEVEL SECURITY;
ALTER TABLE request_engine.operational_recovery_autonomy_policies
  FORCE ROW LEVEL SECURITY;
CREATE POLICY operational_recovery_autonomy_policies_tenant_policy
  ON request_engine.operational_recovery_autonomy_policies
  USING (organization_id = request_engine.current_organization_id())
  WITH CHECK (organization_id = request_engine.current_organization_id());

REVOKE ALL ON request_engine.operational_recovery_autonomy_policies FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE
  ON request_engine.operational_recovery_autonomy_policies TO request_engine_app;
GRANT ALL PRIVILEGES
  ON request_engine.operational_recovery_autonomy_policies TO request_engine_admin;

RESET ROLE;
RESET search_path;
"""


def upgrade() -> None:
    op.execute(_SQL)


def downgrade() -> None:
    raise RuntimeError("0021 introduces the recovery autonomy envelope and is not reversible")
