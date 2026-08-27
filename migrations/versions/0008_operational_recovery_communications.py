"""Add F5 operational recovery proposal and execution facts.

Revision ID: 0008_operational_recovery
Revises: 0007_live_capacity
Create Date: 2026-08-26
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008_operational_recovery"
down_revision: str | Sequence[str] | None = "0007_live_capacity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SQL = r"""
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, request_read, pg_catalog;

CREATE TABLE request_engine.operational_recovery_proposals (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL REFERENCES request_engine.organizations(id),
    service_queue_id uuid NOT NULL,
    resource_id uuid NOT NULL,
    location_id uuid NOT NULL,
    created_by_principal_id uuid NOT NULL,
    idempotency_key text NOT NULL,
    command_fingerprint text NOT NULL,
    observed_at timestamptz NOT NULL,
    horizon_end timestamptz NOT NULL,
    source_fingerprint text NOT NULL,
    proposal_fingerprint text NOT NULL,
    executable_capacity_seconds integer NOT NULL,
    committed_capacity_seconds integer NOT NULL,
    shortfall_seconds integer NOT NULL,
    snapshot jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, id),
    UNIQUE (organization_id, created_by_principal_id, idempotency_key),
    FOREIGN KEY (organization_id, service_queue_id)
      REFERENCES request_engine.service_queues (organization_id, id),
    FOREIGN KEY (organization_id, resource_id)
      REFERENCES request_engine.resources (organization_id, id),
    FOREIGN KEY (organization_id, location_id)
      REFERENCES request_engine.locations (organization_id, id),
    FOREIGN KEY (organization_id, created_by_principal_id)
      REFERENCES request_engine.principals (organization_id, id),
    CHECK (btrim(idempotency_key) <> ''),
    CHECK (btrim(command_fingerprint) <> ''),
    CHECK (horizon_end > observed_at),
    CHECK (btrim(source_fingerprint) <> ''),
    CHECK (btrim(proposal_fingerprint) <> ''),
    CHECK (executable_capacity_seconds >= 0),
    CHECK (committed_capacity_seconds >= 0),
    CHECK (shortfall_seconds > 0),
    CHECK (jsonb_typeof(snapshot) = 'object')
);
CREATE INDEX operational_recovery_proposals_queue_created_idx
  ON request_engine.operational_recovery_proposals
     (organization_id, service_queue_id, created_at DESC);

CREATE FUNCTION request_engine.guard_operational_recovery_proposal()
RETURNS trigger LANGUAGE plpgsql AS $function$
BEGIN
    RAISE EXCEPTION 'OperationalRecoveryProposal is immutable'
        USING ERRCODE = '23514';
END
$function$;
CREATE TRIGGER operational_recovery_proposals_immutable
BEFORE UPDATE OR DELETE ON request_engine.operational_recovery_proposals
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_operational_recovery_proposal();

CREATE TABLE request_engine.operational_recovery_executions (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL REFERENCES request_engine.organizations(id),
    proposal_id uuid NOT NULL,
    reservation_id uuid NOT NULL,
    executed_by_principal_id uuid NOT NULL,
    idempotency_key text NOT NULL,
    command_fingerprint text NOT NULL,
    source_fingerprint text NOT NULL,
    proposal_fingerprint text NOT NULL,
    original_reservation_revision bigint NOT NULL,
    resulting_reservation_revision bigint,
    target jsonb NOT NULL,
    status text NOT NULL DEFAULT 'prepared',
    failure_code text,
    notification_requested boolean NOT NULL DEFAULT true,
    communication_task_id uuid,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    completed_at timestamptz,
    UNIQUE (organization_id, id),
    UNIQUE (organization_id, proposal_id, reservation_id),
    UNIQUE (organization_id, executed_by_principal_id, idempotency_key),
    UNIQUE (organization_id, communication_task_id),
    FOREIGN KEY (organization_id, proposal_id)
      REFERENCES request_engine.operational_recovery_proposals (organization_id, id),
    FOREIGN KEY (organization_id, reservation_id)
      REFERENCES request_engine.reservations (organization_id, id),
    FOREIGN KEY (organization_id, executed_by_principal_id)
      REFERENCES request_engine.principals (organization_id, id),
    FOREIGN KEY (organization_id, communication_task_id)
      REFERENCES request_engine.communication_tasks (organization_id, id),
    CHECK (btrim(idempotency_key) <> ''),
    CHECK (btrim(command_fingerprint) <> ''),
    CHECK (btrim(source_fingerprint) <> ''),
    CHECK (btrim(proposal_fingerprint) <> ''),
    CHECK (original_reservation_revision > 0),
    CHECK (jsonb_typeof(target) = 'object'),
    CHECK (status IN ('prepared', 'succeeded', 'rejected')),
    CHECK (
        (status = 'prepared'
         AND resulting_reservation_revision IS NULL
         AND failure_code IS NULL
         AND completed_at IS NULL
         AND communication_task_id IS NULL)
        OR
        (status = 'succeeded'
         AND resulting_reservation_revision IS NOT NULL
         AND resulting_reservation_revision = original_reservation_revision + 1
         AND failure_code IS NULL
         AND completed_at IS NOT NULL)
        OR
        (status = 'rejected'
         AND resulting_reservation_revision IS NULL
         AND failure_code IS NOT NULL
         AND btrim(failure_code) <> ''
         AND completed_at IS NOT NULL
         AND communication_task_id IS NULL)
    ),
    CHECK (completed_at IS NULL OR completed_at >= created_at),
    CHECK (
        communication_task_id IS NULL
        OR (notification_requested AND status = 'succeeded')
    )
);

CREATE FUNCTION request_engine.guard_operational_recovery_execution()
RETURNS trigger LANGUAGE plpgsql AS $function$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'OperationalRecoveryExecution is append-preserving'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.organization_id IS DISTINCT FROM NEW.organization_id
       OR OLD.id IS DISTINCT FROM NEW.id
       OR OLD.proposal_id IS DISTINCT FROM NEW.proposal_id
       OR OLD.reservation_id IS DISTINCT FROM NEW.reservation_id
       OR OLD.executed_by_principal_id IS DISTINCT FROM NEW.executed_by_principal_id
       OR OLD.idempotency_key IS DISTINCT FROM NEW.idempotency_key
       OR OLD.command_fingerprint IS DISTINCT FROM NEW.command_fingerprint
       OR OLD.source_fingerprint IS DISTINCT FROM NEW.source_fingerprint
       OR OLD.proposal_fingerprint IS DISTINCT FROM NEW.proposal_fingerprint
       OR OLD.original_reservation_revision IS DISTINCT FROM NEW.original_reservation_revision
       OR OLD.target IS DISTINCT FROM NEW.target
       OR OLD.notification_requested IS DISTINCT FROM NEW.notification_requested
       OR OLD.created_at IS DISTINCT FROM NEW.created_at THEN
        RAISE EXCEPTION 'OperationalRecoveryExecution identity is immutable'
            USING ERRCODE = '23514';
    END IF;

    IF OLD.status = 'prepared'
       AND NEW.status IN ('succeeded', 'rejected')
       AND NEW.communication_task_id IS NULL THEN
        RETURN NEW;
    END IF;

    IF OLD.status = 'succeeded'
       AND NEW.status = 'succeeded'
       AND OLD.communication_task_id IS NULL
       AND NEW.communication_task_id IS NOT NULL
       AND OLD.resulting_reservation_revision IS NOT DISTINCT FROM
           NEW.resulting_reservation_revision
       AND OLD.failure_code IS NOT DISTINCT FROM NEW.failure_code
       AND OLD.completed_at IS NOT DISTINCT FROM NEW.completed_at THEN
        RETURN NEW;
    END IF;

    RAISE EXCEPTION 'invalid OperationalRecoveryExecution transition % -> %',
        OLD.status, NEW.status USING ERRCODE = '23514';
END
$function$;
CREATE TRIGGER operational_recovery_executions_guard
BEFORE UPDATE OR DELETE ON request_engine.operational_recovery_executions
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_operational_recovery_execution();

ALTER TABLE request_engine.operational_recovery_proposals ENABLE ROW LEVEL SECURITY;
ALTER TABLE request_engine.operational_recovery_proposals FORCE ROW LEVEL SECURITY;
CREATE POLICY operational_recovery_proposals_tenant_policy
  ON request_engine.operational_recovery_proposals
  USING (organization_id = request_engine.current_organization_id())
  WITH CHECK (organization_id = request_engine.current_organization_id());

ALTER TABLE request_engine.operational_recovery_executions ENABLE ROW LEVEL SECURITY;
ALTER TABLE request_engine.operational_recovery_executions FORCE ROW LEVEL SECURITY;
CREATE POLICY operational_recovery_executions_tenant_policy
  ON request_engine.operational_recovery_executions
  USING (organization_id = request_engine.current_organization_id())
  WITH CHECK (organization_id = request_engine.current_organization_id());

REVOKE ALL ON request_engine.operational_recovery_proposals,
  request_engine.operational_recovery_executions FROM PUBLIC;
GRANT SELECT, INSERT ON request_engine.operational_recovery_proposals TO request_engine_app;
GRANT SELECT, INSERT ON request_engine.operational_recovery_executions TO request_engine_app;
GRANT UPDATE (
    status,
    resulting_reservation_revision,
    failure_code,
    completed_at,
    communication_task_id
) ON request_engine.operational_recovery_executions TO request_engine_app;
GRANT ALL PRIVILEGES ON request_engine.operational_recovery_proposals,
  request_engine.operational_recovery_executions TO request_engine_admin;

RESET ROLE;
RESET search_path;
"""


def upgrade() -> None:
    op.execute(_SQL)


def downgrade() -> None:
    raise RuntimeError(
        "0008 introduces durable F5 recovery facts and is not reversible in place"
    )
