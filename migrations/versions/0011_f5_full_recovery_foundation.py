"""Add full F5 recovery workflow foundation.

Revision ID: 0011_f5_full_recovery
Revises: 0010_f5_source_writer
Create Date: 2026-08-27
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011_f5_full_recovery"
down_revision: str | Sequence[str] | None = "0010_f5_source_writer"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SQL = r"""
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, request_read, request_cmd, pg_catalog;

CREATE TABLE request_engine.service_queue_intake_controls (
    organization_id uuid NOT NULL,
    service_queue_id uuid NOT NULL,
    accepting boolean NOT NULL DEFAULT true,
    reason text,
    effective_until timestamptz,
    revision bigint NOT NULL DEFAULT 1,
    updated_by_principal_id uuid,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (organization_id, service_queue_id),
    FOREIGN KEY (organization_id, service_queue_id)
      REFERENCES request_engine.service_queues (organization_id, id),
    FOREIGN KEY (organization_id, updated_by_principal_id)
      REFERENCES request_engine.principals (organization_id, id),
    CHECK (revision > 0),
    CHECK (reason IS NULL OR btrim(reason) <> '')
);

INSERT INTO request_engine.service_queue_intake_controls (
    organization_id, service_queue_id
)
SELECT organization_id, id
FROM request_engine.service_queues
ON CONFLICT DO NOTHING;

CREATE FUNCTION request_engine.initialize_service_queue_intake_control()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = request_engine, pg_catalog
AS $function$
BEGIN
    INSERT INTO request_engine.service_queue_intake_controls (
        organization_id, service_queue_id
    ) VALUES (NEW.organization_id, NEW.id)
    ON CONFLICT DO NOTHING;
    RETURN NEW;
END
$function$;
REVOKE ALL ON FUNCTION request_engine.initialize_service_queue_intake_control() FROM PUBLIC;

CREATE TRIGGER service_queues_initialize_intake_control
AFTER INSERT ON request_engine.service_queues
FOR EACH ROW EXECUTE FUNCTION request_engine.initialize_service_queue_intake_control();

ALTER TABLE request_engine.service_queue_intake_controls ENABLE ROW LEVEL SECURITY;
ALTER TABLE request_engine.service_queue_intake_controls FORCE ROW LEVEL SECURITY;
CREATE POLICY service_queue_intake_controls_tenant_policy
  ON request_engine.service_queue_intake_controls
  USING (organization_id = request_engine.current_organization_id())
  WITH CHECK (organization_id = request_engine.current_organization_id());
CREATE POLICY service_queue_intake_controls_trigger_writer_policy
  ON request_engine.service_queue_intake_controls
  FOR INSERT
  TO request_engine_schema_owner
  WITH CHECK (pg_trigger_depth() > 0);

REVOKE ALL ON request_engine.service_queue_intake_controls FROM PUBLIC;
GRANT SELECT, UPDATE ON request_engine.service_queue_intake_controls TO request_engine_app;
GRANT ALL PRIVILEGES ON request_engine.service_queue_intake_controls TO request_engine_admin;

CREATE TABLE request_engine.operational_recovery_incidents (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL REFERENCES request_engine.organizations(id),
    service_queue_id uuid NOT NULL,
    resource_id uuid NOT NULL,
    location_id uuid NOT NULL,
    status text NOT NULL DEFAULT 'open',
    impact_kind text NOT NULL,
    escalation_level integer NOT NULL DEFAULT 0,
    source_revision bigint NOT NULL,
    source_fingerprint text NOT NULL,
    current_proposal_id uuid,
    opened_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    last_assessed_at timestamptz NOT NULL,
    resolved_at timestamptz,
    revision bigint NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, id),
    FOREIGN KEY (organization_id, service_queue_id)
      REFERENCES request_engine.service_queues (organization_id, id),
    FOREIGN KEY (organization_id, resource_id)
      REFERENCES request_engine.resources (organization_id, id),
    FOREIGN KEY (organization_id, location_id)
      REFERENCES request_engine.locations (organization_id, id),
    FOREIGN KEY (organization_id, current_proposal_id)
      REFERENCES request_engine.operational_recovery_proposals (organization_id, id),
    CHECK (status IN ('open', 'mitigating', 'resolved')),
    CHECK (impact_kind IN ('delay', 'capacity_shortfall', 'indeterminate')),
    CHECK (escalation_level >= 0),
    CHECK (source_revision > 0),
    CHECK (btrim(source_fingerprint) <> ''),
    CHECK (revision > 0),
    CHECK ((status = 'resolved') = (resolved_at IS NOT NULL))
);
CREATE UNIQUE INDEX operational_recovery_one_unresolved_scope_uq
  ON request_engine.operational_recovery_incidents (organization_id, service_queue_id)
  WHERE status <> 'resolved';
CREATE INDEX operational_recovery_incidents_scope_idx
  ON request_engine.operational_recovery_incidents
  (organization_id, service_queue_id, last_assessed_at DESC);

CREATE TABLE request_engine.operational_recovery_actions (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL REFERENCES request_engine.organizations(id),
    incident_id uuid NOT NULL,
    action_kind text NOT NULL,
    status text NOT NULL DEFAULT 'prepared',
    principal_id uuid NOT NULL,
    idempotency_key text NOT NULL,
    command_fingerprint text NOT NULL,
    expected_source_revision bigint NOT NULL,
    payload jsonb NOT NULL,
    owner_steps jsonb NOT NULL DEFAULT '{}'::jsonb,
    failure_code text,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    started_at timestamptz,
    completed_at timestamptz,
    UNIQUE (organization_id, id),
    UNIQUE (organization_id, principal_id, idempotency_key),
    FOREIGN KEY (organization_id, incident_id)
      REFERENCES request_engine.operational_recovery_incidents (organization_id, id),
    FOREIGN KEY (organization_id, principal_id)
      REFERENCES request_engine.principals (organization_id, id),
    CHECK (action_kind IN (
      'stop_intake', 'reopen_intake', 'extend_day',
      'reschedule', 'replace_resource', 'communicate_impact'
    )),
    CHECK (status IN ('prepared', 'running', 'succeeded', 'rejected', 'partially_applied')),
    CHECK (expected_source_revision > 0),
    CHECK (btrim(idempotency_key) <> ''),
    CHECK (btrim(command_fingerprint) <> ''),
    CHECK (jsonb_typeof(payload) = 'object'),
    CHECK (jsonb_typeof(owner_steps) = 'object')
);
CREATE INDEX operational_recovery_actions_incident_idx
  ON request_engine.operational_recovery_actions
  (organization_id, incident_id, created_at, id);

ALTER TABLE request_engine.operational_recovery_incidents ENABLE ROW LEVEL SECURITY;
ALTER TABLE request_engine.operational_recovery_incidents FORCE ROW LEVEL SECURITY;
CREATE POLICY operational_recovery_incidents_tenant_policy
  ON request_engine.operational_recovery_incidents
  USING (organization_id = request_engine.current_organization_id())
  WITH CHECK (organization_id = request_engine.current_organization_id());

ALTER TABLE request_engine.operational_recovery_actions ENABLE ROW LEVEL SECURITY;
ALTER TABLE request_engine.operational_recovery_actions FORCE ROW LEVEL SECURITY;
CREATE POLICY operational_recovery_actions_tenant_policy
  ON request_engine.operational_recovery_actions
  USING (organization_id = request_engine.current_organization_id())
  WITH CHECK (organization_id = request_engine.current_organization_id());

REVOKE ALL ON request_engine.operational_recovery_incidents FROM PUBLIC;
REVOKE ALL ON request_engine.operational_recovery_actions FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE ON request_engine.operational_recovery_incidents TO request_engine_app;
GRANT SELECT, INSERT, UPDATE ON request_engine.operational_recovery_actions TO request_engine_app;
GRANT ALL PRIVILEGES ON request_engine.operational_recovery_incidents TO request_engine_admin;
GRANT ALL PRIVILEGES ON request_engine.operational_recovery_actions TO request_engine_admin;

RESET ROLE;
RESET search_path;
"""


def upgrade() -> None:
    op.execute(_SQL)


def downgrade() -> None:
    raise RuntimeError("0011 introduces durable full-F5 recovery workflow state and is not reversible")
