"""Add F4 live capacity projection configuration.

Revision ID: 0007_live_capacity
Revises: 0006_f3_fact_hardening
Create Date: 2026-08-26
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007_live_capacity"
down_revision: str | Sequence[str] | None = "0006_f3_fact_hardening"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SQL = r"""
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, request_read, pg_catalog;

CREATE TABLE request_engine.live_capacity_projection_policies (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL REFERENCES request_engine.organizations(id),
    service_queue_id uuid NOT NULL,
    resource_id uuid NOT NULL,
    location_id uuid NOT NULL,
    active boolean NOT NULL DEFAULT true,
    revision bigint NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, id),
    UNIQUE (organization_id, service_queue_id),
    FOREIGN KEY (organization_id, service_queue_id)
      REFERENCES request_engine.service_queues (organization_id, id),
    FOREIGN KEY (organization_id, resource_id)
      REFERENCES request_engine.resources (organization_id, id),
    FOREIGN KEY (organization_id, location_id)
      REFERENCES request_engine.locations (organization_id, id),
    CHECK (revision > 0)
);

CREATE TABLE request_engine.live_capacity_workload_estimate_policies (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL REFERENCES request_engine.organizations(id),
    workload_classification_id uuid NOT NULL,
    duration_seconds integer NOT NULL,
    active boolean NOT NULL DEFAULT true,
    revision bigint NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, id),
    UNIQUE (organization_id, workload_classification_id),
    FOREIGN KEY (organization_id, workload_classification_id)
      REFERENCES request_engine.operational_workload_classifications (organization_id, id),
    CHECK (duration_seconds > 0),
    CHECK (revision > 0)
);

CREATE FUNCTION request_engine.guard_live_capacity_projection_policy()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'LiveCapacityProjectionPolicy is durable configuration; deactivate it'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.organization_id IS DISTINCT FROM NEW.organization_id
       OR OLD.id IS DISTINCT FROM NEW.id
       OR OLD.service_queue_id IS DISTINCT FROM NEW.service_queue_id THEN
        RAISE EXCEPTION 'LiveCapacityProjectionPolicy identity cannot be retargeted'
            USING ERRCODE = '23514';
    END IF;
    IF NEW IS DISTINCT FROM OLD AND NEW.revision <> OLD.revision + 1 THEN
        RAISE EXCEPTION 'LiveCapacityProjectionPolicy revision must advance exactly one step'
            USING ERRCODE = '23514';
    END IF;
    IF NEW IS DISTINCT FROM OLD THEN
        NEW.updated_at := clock_timestamp();
    END IF;
    RETURN NEW;
END
$function$;

CREATE TRIGGER live_capacity_projection_policies_guard_transition
BEFORE UPDATE OR DELETE ON request_engine.live_capacity_projection_policies
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_live_capacity_projection_policy();

CREATE FUNCTION request_engine.guard_live_capacity_workload_estimate_policy()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'LiveCapacityWorkloadEstimatePolicy is durable configuration; deactivate it'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.organization_id IS DISTINCT FROM NEW.organization_id
       OR OLD.id IS DISTINCT FROM NEW.id
       OR OLD.workload_classification_id IS DISTINCT FROM NEW.workload_classification_id THEN
        RAISE EXCEPTION 'LiveCapacityWorkloadEstimatePolicy identity cannot be retargeted'
            USING ERRCODE = '23514';
    END IF;
    IF NEW IS DISTINCT FROM OLD AND NEW.revision <> OLD.revision + 1 THEN
        RAISE EXCEPTION 'LiveCapacityWorkloadEstimatePolicy revision must advance exactly one step'
            USING ERRCODE = '23514';
    END IF;
    IF NEW IS DISTINCT FROM OLD THEN
        NEW.updated_at := clock_timestamp();
    END IF;
    RETURN NEW;
END
$function$;

CREATE TRIGGER live_capacity_workload_estimate_policies_guard_transition
BEFORE UPDATE OR DELETE ON request_engine.live_capacity_workload_estimate_policies
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_live_capacity_workload_estimate_policy();

ALTER TABLE request_engine.live_capacity_projection_policies ENABLE ROW LEVEL SECURITY;
ALTER TABLE request_engine.live_capacity_projection_policies FORCE ROW LEVEL SECURITY;
CREATE POLICY live_capacity_projection_policies_tenant_policy
  ON request_engine.live_capacity_projection_policies
  USING (organization_id = request_engine.current_organization_id())
  WITH CHECK (organization_id = request_engine.current_organization_id());

ALTER TABLE request_engine.live_capacity_workload_estimate_policies ENABLE ROW LEVEL SECURITY;
ALTER TABLE request_engine.live_capacity_workload_estimate_policies FORCE ROW LEVEL SECURITY;
CREATE POLICY live_capacity_workload_estimate_policies_tenant_policy
  ON request_engine.live_capacity_workload_estimate_policies
  USING (organization_id = request_engine.current_organization_id())
  WITH CHECK (organization_id = request_engine.current_organization_id());

REVOKE ALL ON request_engine.live_capacity_projection_policies,
  request_engine.live_capacity_workload_estimate_policies FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE ON request_engine.live_capacity_projection_policies,
  request_engine.live_capacity_workload_estimate_policies TO request_engine_app;
GRANT ALL PRIVILEGES ON request_engine.live_capacity_projection_policies,
  request_engine.live_capacity_workload_estimate_policies TO request_engine_admin;

RESET ROLE;
RESET search_path;
"""


def upgrade() -> None:
    op.execute(_SQL)


def downgrade() -> None:
    raise RuntimeError(
        "0007 introduces durable F4 projection configuration and is not reversible in place"
    )
