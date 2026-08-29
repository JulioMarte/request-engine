"""Add durable F5 escalation/communication policy outcomes.

Revision ID: 0017_f5_escalation_policy
Revises: 0016_f5_bump_guard_freshness
Create Date: 2026-08-28
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0017_f5_escalation_policy"
down_revision: str | Sequence[str] | None = "0016_f5_bump_guard_freshness"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SQL = r"""
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, request_read, request_cmd, pg_catalog;

CREATE TABLE request_engine.operational_recovery_escalations (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL REFERENCES request_engine.organizations(id),
    incident_id uuid NOT NULL,
    source_revision bigint NOT NULL,
    escalation_level integer NOT NULL,
    operator_escalation_required boolean NOT NULL,
    escalation_reason text,
    customer_impact_required boolean NOT NULL,
    impact_recipient_party_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    source_fingerprint text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, incident_id, source_revision),
    FOREIGN KEY (organization_id, incident_id)
      REFERENCES request_engine.operational_recovery_incidents (organization_id, id),
    CHECK (source_revision > 0),
    CHECK (escalation_level >= 0),
    CHECK (operator_escalation_required = (escalation_reason IS NOT NULL)),
    CHECK (escalation_reason IS NULL OR escalation_reason IN
      ('newly_material', 'worsening_severity')),
    CHECK (jsonb_typeof(impact_recipient_party_ids) = 'array'),
    CHECK (customer_impact_required = (jsonb_array_length(impact_recipient_party_ids) > 0)),
    CHECK (btrim(source_fingerprint) <> '')
);
CREATE INDEX operational_recovery_escalations_incident_idx
  ON request_engine.operational_recovery_escalations
  (organization_id, incident_id, source_revision DESC);

CREATE FUNCTION request_engine.guard_operational_recovery_escalation()
RETURNS trigger LANGUAGE plpgsql AS $function$
BEGIN
    RAISE EXCEPTION 'OperationalRecoveryEscalation is immutable'
        USING ERRCODE = '23514';
END
$function$;
CREATE TRIGGER operational_recovery_escalations_immutable
BEFORE UPDATE OR DELETE ON request_engine.operational_recovery_escalations
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_operational_recovery_escalation();

ALTER TABLE request_engine.operational_recovery_escalations ENABLE ROW LEVEL SECURITY;
ALTER TABLE request_engine.operational_recovery_escalations FORCE ROW LEVEL SECURITY;
CREATE POLICY operational_recovery_escalations_tenant_policy
  ON request_engine.operational_recovery_escalations
  USING (organization_id = request_engine.current_organization_id())
  WITH CHECK (organization_id = request_engine.current_organization_id());

REVOKE ALL ON request_engine.operational_recovery_escalations FROM PUBLIC;
GRANT SELECT, INSERT ON request_engine.operational_recovery_escalations TO request_engine_app;
GRANT ALL PRIVILEGES ON request_engine.operational_recovery_escalations TO request_engine_admin;

RESET ROLE;
RESET search_path;
"""


def upgrade() -> None:
    op.execute(_SQL)


def downgrade() -> None:
    raise RuntimeError("0017 introduces durable F5 escalation policy facts and is not reversible")
