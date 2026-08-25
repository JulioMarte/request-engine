"""Add F3 live service operations.

Revision ID: 0005_live_service_ops
Revises: 0004_f2_discovery
Create Date: 2026-08-25
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005_live_service_ops"
down_revision: str | Sequence[str] | None = "0004_f2_discovery"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SQL = r"""
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, request_read, pg_catalog;

CREATE TABLE request_engine.operational_workload_classifications (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL REFERENCES request_engine.organizations(id),
    workload_key text NOT NULL,
    display_name text NOT NULL,
    active boolean NOT NULL DEFAULT true,
    revision bigint NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, id),
    UNIQUE (organization_id, workload_key),
    CHECK (btrim(workload_key) <> ''),
    CHECK (btrim(display_name) <> ''),
    CHECK (revision > 0)
);

ALTER TABLE request_engine.queue_entries
    ADD COLUMN arrived_at timestamptz,
    ADD COLUMN expected_workload_classification_id uuid;
UPDATE request_engine.queue_entries SET arrived_at = admitted_at WHERE arrived_at IS NULL;
ALTER TABLE request_engine.queue_entries
    ALTER COLUMN arrived_at SET NOT NULL,
    ALTER COLUMN arrived_at SET DEFAULT statement_timestamp(),
    ALTER COLUMN admitted_at SET DEFAULT statement_timestamp(),
    ADD CONSTRAINT queue_entries_expected_workload_fk
      FOREIGN KEY (organization_id, expected_workload_classification_id)
      REFERENCES request_engine.operational_workload_classifications (organization_id, id),
    ADD CONSTRAINT queue_entries_arrival_order_ck CHECK (arrived_at <= admitted_at);

CREATE TABLE request_engine.service_sessions (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL,
    queue_entry_id uuid NOT NULL,
    resource_id uuid NOT NULL,
    location_id uuid NOT NULL,
    actual_workload_classification_id uuid,
    status text NOT NULL DEFAULT 'active',
    started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    completed_at timestamptz,
    revision bigint NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, id),
    UNIQUE (organization_id, queue_entry_id),
    FOREIGN KEY (organization_id, queue_entry_id)
      REFERENCES request_engine.queue_entries (organization_id, id),
    FOREIGN KEY (organization_id, resource_id)
      REFERENCES request_engine.resources (organization_id, id),
    FOREIGN KEY (organization_id, location_id)
      REFERENCES request_engine.locations (organization_id, id),
    FOREIGN KEY (organization_id, actual_workload_classification_id)
      REFERENCES request_engine.operational_workload_classifications (organization_id, id),
    CHECK (status IN ('active', 'paused', 'completed')),
    CHECK (revision > 0),
    CHECK ((status = 'completed') = (completed_at IS NOT NULL)),
    CHECK (completed_at IS NULL OR completed_at >= started_at)
);
CREATE UNIQUE INDEX service_sessions_one_live_resource_uq
  ON request_engine.service_sessions (organization_id, resource_id)
  WHERE status IN ('active', 'paused');
CREATE INDEX service_sessions_queue_idx
  ON request_engine.service_sessions (organization_id, queue_entry_id);

CREATE TABLE request_engine.service_session_interruptions (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL,
    service_session_id uuid NOT NULL,
    kind text NOT NULL,
    started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    ended_at timestamptz,
    started_by_principal_id uuid NOT NULL,
    ended_by_principal_id uuid,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, id),
    FOREIGN KEY (organization_id, service_session_id)
      REFERENCES request_engine.service_sessions (organization_id, id),
    FOREIGN KEY (organization_id, started_by_principal_id)
      REFERENCES request_engine.principals (organization_id, id),
    FOREIGN KEY (organization_id, ended_by_principal_id)
      REFERENCES request_engine.principals (organization_id, id),
    CHECK (kind IN ('emergency', 'break', 'administrative', 'other_operational')),
    CHECK (ended_at IS NULL OR ended_at >= started_at)
);
CREATE UNIQUE INDEX service_session_interruptions_one_open_uq
  ON request_engine.service_session_interruptions (organization_id, service_session_id)
  WHERE ended_at IS NULL;

CREATE TABLE request_engine.resource_activities (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL,
    resource_id uuid NOT NULL,
    location_id uuid,
    activity_kind text NOT NULL,
    started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    ended_at timestamptz,
    started_by_principal_id uuid NOT NULL,
    ended_by_principal_id uuid,
    revision bigint NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, id),
    FOREIGN KEY (organization_id, resource_id)
      REFERENCES request_engine.resources (organization_id, id),
    FOREIGN KEY (organization_id, location_id)
      REFERENCES request_engine.locations (organization_id, id),
    FOREIGN KEY (organization_id, started_by_principal_id)
      REFERENCES request_engine.principals (organization_id, id),
    FOREIGN KEY (organization_id, ended_by_principal_id)
      REFERENCES request_engine.principals (organization_id, id),
    CHECK (activity_kind IN ('break', 'emergency', 'administrative', 'other_operational')),
    CHECK (ended_at IS NULL OR ended_at >= started_at),
    CONSTRAINT resource_activities_end_actor_ck
      CHECK ((ended_at IS NULL) = (ended_by_principal_id IS NULL)),
    CHECK (revision > 0)
);
CREATE UNIQUE INDEX resource_activities_one_open_resource_uq
  ON request_engine.resource_activities (organization_id, resource_id)
  WHERE ended_at IS NULL;

CREATE FUNCTION request_engine.guard_live_resource_occupation()
RETURNS trigger LANGUAGE plpgsql AS $function$
DECLARE
    v_validate_assignment boolean;
BEGIN
    PERFORM 1 FROM request_engine.resources
     WHERE organization_id = NEW.organization_id AND id = NEW.resource_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Resource % does not exist', NEW.resource_id USING ERRCODE = '23503';
    END IF;

    IF TG_TABLE_NAME = 'service_sessions' THEN
        v_validate_assignment := TG_OP = 'INSERT';
        IF TG_OP = 'UPDATE' THEN
            v_validate_assignment := NEW.resource_id IS DISTINCT FROM OLD.resource_id
                OR NEW.location_id IS DISTINCT FROM OLD.location_id
                OR NEW.started_at IS DISTINCT FROM OLD.started_at;
        END IF;
        IF v_validate_assignment AND NOT EXISTS (
            SELECT 1 FROM request_engine.resource_location_assignments a
             WHERE a.organization_id = NEW.organization_id
               AND a.resource_id = NEW.resource_id
               AND a.location_id = NEW.location_id
               AND a.status = 'active'
               AND a.effective_during @> NEW.started_at
        ) THEN
            RAISE EXCEPTION 'Resource % is not assigned to Location % at execution time',
                NEW.resource_id, NEW.location_id USING ERRCODE = '23514';
        END IF;
        IF NEW.status IN ('active', 'paused') AND EXISTS (
            SELECT 1 FROM request_engine.resource_activities a
             WHERE a.organization_id = NEW.organization_id
               AND a.resource_id = NEW.resource_id AND a.ended_at IS NULL
        ) THEN
            RAISE EXCEPTION 'Resource % has an open ResourceActivity', NEW.resource_id
                USING ERRCODE = '23P01';
        END IF;
    ELSIF TG_TABLE_NAME = 'resource_activities' THEN
        v_validate_assignment := TG_OP = 'INSERT';
        IF TG_OP = 'UPDATE' THEN
            v_validate_assignment := NEW.resource_id IS DISTINCT FROM OLD.resource_id
                OR NEW.location_id IS DISTINCT FROM OLD.location_id
                OR NEW.started_at IS DISTINCT FROM OLD.started_at;
        END IF;
        IF v_validate_assignment AND NEW.location_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM request_engine.resource_location_assignments a
             WHERE a.organization_id = NEW.organization_id
               AND a.resource_id = NEW.resource_id
               AND a.location_id = NEW.location_id
               AND a.status = 'active'
               AND a.effective_during @> NEW.started_at
        ) THEN
            RAISE EXCEPTION 'Resource % is not assigned to Location % at activity start',
                NEW.resource_id, NEW.location_id USING ERRCODE = '23514';
        END IF;
        IF NEW.ended_at IS NULL AND EXISTS (
            SELECT 1 FROM request_engine.service_sessions s
             WHERE s.organization_id = NEW.organization_id
               AND s.resource_id = NEW.resource_id AND s.status IN ('active', 'paused')
        ) THEN
            RAISE EXCEPTION 'Resource % has a live ServiceSession', NEW.resource_id
                USING ERRCODE = '23P01';
        END IF;
    ELSE
        RAISE EXCEPTION 'guard_live_resource_occupation attached to unsupported relation %',
            TG_TABLE_NAME USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END
$function$;
CREATE TRIGGER service_sessions_guard_resource_occupation
BEFORE INSERT OR UPDATE OF resource_id, status ON request_engine.service_sessions
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_live_resource_occupation();
CREATE TRIGGER resource_activities_guard_resource_occupation
BEFORE INSERT OR UPDATE OF resource_id, ended_at ON request_engine.resource_activities
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_live_resource_occupation();

CREATE FUNCTION request_engine.guard_resource_activity_transition()
RETURNS trigger LANGUAGE plpgsql AS $function$
BEGIN
    IF OLD.organization_id IS DISTINCT FROM NEW.organization_id
       OR OLD.resource_id IS DISTINCT FROM NEW.resource_id
       OR OLD.location_id IS DISTINCT FROM NEW.location_id
       OR OLD.activity_kind IS DISTINCT FROM NEW.activity_kind
       OR OLD.started_at IS DISTINCT FROM NEW.started_at THEN
        RAISE EXCEPTION 'ResourceActivity identity cannot be retargeted'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.ended_at IS NOT NULL AND NEW IS DISTINCT FROM OLD THEN
        RAISE EXCEPTION 'ended ResourceActivity is immutable' USING ERRCODE = '23514';
    END IF;
    IF NEW IS DISTINCT FROM OLD AND NEW.revision <> OLD.revision + 1 THEN
        RAISE EXCEPTION 'ResourceActivity revision must advance exactly one step'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$;
CREATE TRIGGER resource_activities_guard_transition
BEFORE UPDATE ON request_engine.resource_activities
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_resource_activity_transition();

CREATE FUNCTION request_engine.guard_service_session_transition()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    IF OLD.organization_id <> NEW.organization_id OR OLD.queue_entry_id <> NEW.queue_entry_id
       OR OLD.resource_id <> NEW.resource_id OR OLD.location_id <> NEW.location_id THEN
        RAISE EXCEPTION 'ServiceSession execution identity cannot be retargeted' USING ERRCODE = '23514';
    END IF;
    IF NEW.status <> OLD.status AND NOT (
        (OLD.status = 'active' AND NEW.status IN ('paused', 'completed')) OR
        (OLD.status = 'paused' AND NEW.status = 'active')
    ) THEN
        RAISE EXCEPTION 'invalid ServiceSession transition from % to %', OLD.status, NEW.status
            USING ERRCODE = '23514';
    END IF;
    IF NEW.revision <> OLD.revision + 1 AND NEW IS DISTINCT FROM OLD THEN
        RAISE EXCEPTION 'ServiceSession revision must advance exactly one step' USING ERRCODE = '23514';
    END IF;
    IF NEW.started_at <> OLD.started_at THEN
        RAISE EXCEPTION 'ServiceSession started_at is immutable' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$;
CREATE TRIGGER service_sessions_guard_transition
BEFORE UPDATE ON request_engine.service_sessions
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_service_session_transition();

CREATE FUNCTION request_engine.assert_service_queue_coherence()
RETURNS trigger LANGUAGE plpgsql AS $function$
DECLARE
    v_entry request_engine.queue_entries%ROWTYPE;
    v_session request_engine.service_sessions%ROWTYPE;
    v_entry_id uuid;
BEGIN
    IF TG_TABLE_NAME = 'service_sessions' THEN
        v_entry_id := NEW.queue_entry_id;
    ELSE
        v_entry_id := NEW.id;
    END IF;
    SELECT * INTO v_entry FROM request_engine.queue_entries e
     WHERE e.organization_id = NEW.organization_id AND e.id = v_entry_id;
    SELECT * INTO v_session FROM request_engine.service_sessions s
     WHERE s.organization_id = NEW.organization_id AND s.queue_entry_id = v_entry_id;
    IF v_session.id IS NULL THEN
        IF v_entry.status IN ('serving', 'completed')
           AND v_entry.service_started_at IS NOT NULL THEN
            RAISE EXCEPTION 'QueueEntry % execution requires ServiceSession', v_entry_id
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    IF v_entry.called_at IS NULL OR v_session.started_at < v_entry.called_at THEN
        RAISE EXCEPTION 'ServiceSession % cannot start before QueueEntry is called', v_session.id
            USING ERRCODE = '23514';
    END IF;
    IF v_session.status IN ('active', 'paused') AND v_entry.status <> 'serving' THEN
        RAISE EXCEPTION 'live ServiceSession % requires SERVING QueueEntry', v_session.id
            USING ERRCODE = '23514';
    END IF;
    IF v_session.status = 'completed' AND v_entry.status <> 'completed' THEN
        RAISE EXCEPTION 'completed ServiceSession % requires COMPLETED QueueEntry', v_session.id
            USING ERRCODE = '23514';
    END IF;
    IF v_entry.service_started_at IS DISTINCT FROM v_session.started_at
       OR v_entry.completed_at IS DISTINCT FROM v_session.completed_at THEN
        RAISE EXCEPTION 'QueueEntry compatibility timestamps must equal ServiceSession timestamps'
            USING ERRCODE = '23514';
    END IF;
    IF v_entry.status = 'no_show' THEN
        RAISE EXCEPTION 'NO_SHOW QueueEntry cannot have a ServiceSession' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$;
CREATE CONSTRAINT TRIGGER queue_entries_service_session_coherence
AFTER INSERT OR UPDATE ON request_engine.queue_entries
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION request_engine.assert_service_queue_coherence();
CREATE CONSTRAINT TRIGGER service_sessions_queue_entry_coherence
AFTER INSERT OR UPDATE ON request_engine.service_sessions
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION request_engine.assert_service_queue_coherence();

CREATE FUNCTION request_engine.assert_session_interruption_coherence()
RETURNS trigger LANGUAGE plpgsql AS $function$
DECLARE
    v_session_id uuid;
    v_status text;
    v_started_at timestamptz;
    v_completed_at timestamptz;
    v_open bigint;
BEGIN
    IF TG_TABLE_NAME = 'service_sessions' THEN
        v_session_id := NEW.id;
    ELSE
        v_session_id := NEW.service_session_id;
    END IF;
    SELECT status, started_at, completed_at
      INTO v_status, v_started_at, v_completed_at
      FROM request_engine.service_sessions
     WHERE organization_id = NEW.organization_id AND id = v_session_id;
    IF NOT FOUND THEN RETURN NEW; END IF;

    IF EXISTS (
        SELECT 1 FROM request_engine.service_session_interruptions i
         WHERE i.organization_id = NEW.organization_id
           AND i.service_session_id = v_session_id
           AND i.started_at < v_started_at
    ) THEN
        RAISE EXCEPTION 'ServiceSession % interruption cannot predate execution', v_session_id
            USING ERRCODE = '23514';
    END IF;
    IF v_completed_at IS NOT NULL AND EXISTS (
        SELECT 1 FROM request_engine.service_session_interruptions i
         WHERE i.organization_id = NEW.organization_id
           AND i.service_session_id = v_session_id
           AND (i.ended_at IS NULL OR i.ended_at > v_completed_at)
    ) THEN
        RAISE EXCEPTION 'ServiceSession % interruption cannot outlive execution', v_session_id
            USING ERRCODE = '23514';
    END IF;

    SELECT count(*) INTO v_open FROM request_engine.service_session_interruptions
     WHERE organization_id = NEW.organization_id
       AND service_session_id = v_session_id AND ended_at IS NULL;
    IF (v_status = 'paused' AND v_open <> 1) OR (v_status <> 'paused' AND v_open <> 0) THEN
        RAISE EXCEPTION 'ServiceSession % interruption state is incoherent', v_session_id
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$;
CREATE CONSTRAINT TRIGGER service_sessions_interruption_coherence
AFTER INSERT OR UPDATE ON request_engine.service_sessions
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION request_engine.assert_session_interruption_coherence();
CREATE CONSTRAINT TRIGGER interruptions_session_coherence
AFTER INSERT OR UPDATE ON request_engine.service_session_interruptions
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION request_engine.assert_session_interruption_coherence();

ALTER TABLE request_engine.operational_workload_classifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE request_engine.operational_workload_classifications FORCE ROW LEVEL SECURITY;
CREATE POLICY operational_workload_classifications_tenant_policy
  ON request_engine.operational_workload_classifications
  USING (organization_id = request_engine.current_organization_id())
  WITH CHECK (organization_id = request_engine.current_organization_id());
ALTER TABLE request_engine.service_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE request_engine.service_sessions FORCE ROW LEVEL SECURITY;
CREATE POLICY service_sessions_tenant_policy ON request_engine.service_sessions
  USING (organization_id = request_engine.current_organization_id())
  WITH CHECK (organization_id = request_engine.current_organization_id());
ALTER TABLE request_engine.service_session_interruptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE request_engine.service_session_interruptions FORCE ROW LEVEL SECURITY;
CREATE POLICY service_session_interruptions_tenant_policy
  ON request_engine.service_session_interruptions
  USING (organization_id = request_engine.current_organization_id())
  WITH CHECK (organization_id = request_engine.current_organization_id());
ALTER TABLE request_engine.resource_activities ENABLE ROW LEVEL SECURITY;
ALTER TABLE request_engine.resource_activities FORCE ROW LEVEL SECURITY;
CREATE POLICY resource_activities_tenant_policy ON request_engine.resource_activities
  USING (organization_id = request_engine.current_organization_id())
  WITH CHECK (organization_id = request_engine.current_organization_id());

CREATE VIEW request_read.service_queue_status_v2
WITH (security_invoker = true) AS
SELECT q.id AS queue_id, q.organization_id, q.queue_key, q.display_name,
       e.id AS queue_entry_id, e.subject_party_id, e.reservation_id, e.offering_id,
       e.status, e.arrived_at, e.admitted_at, e.called_at,
       e.expected_workload_classification_id,
       s.id AS service_session_id, s.resource_id AS actual_resource_id,
       s.location_id AS actual_location_id, s.actual_workload_classification_id,
       s.status AS service_status, s.started_at AS service_started_at,
       s.completed_at AS service_completed_at,
       e.revision AS queue_revision, s.revision AS service_revision
FROM request_engine.service_queues q
LEFT JOIN request_engine.queue_entries e
  ON e.organization_id = q.organization_id AND e.service_queue_id = q.id
LEFT JOIN request_engine.service_sessions s
  ON s.organization_id = e.organization_id AND s.queue_entry_id = e.id;

CREATE VIEW request_read.service_session_status_v1
WITH (security_invoker = true) AS
SELECT s.id AS service_session_id, s.organization_id, s.queue_entry_id,
       s.resource_id, s.location_id, s.actual_workload_classification_id,
       s.status, s.started_at, s.completed_at, s.revision,
       COALESCE(i.total_interruption_seconds, 0)::bigint AS interruption_seconds
FROM request_engine.service_sessions s
LEFT JOIN LATERAL (
    SELECT sum(extract(epoch FROM (COALESCE(i.ended_at, clock_timestamp()) - i.started_at)))
             AS total_interruption_seconds
      FROM request_engine.service_session_interruptions i
     WHERE i.organization_id = s.organization_id AND i.service_session_id = s.id
) i ON true;

CREATE VIEW request_read.live_service_staff_v1
WITH (security_invoker = true) AS
SELECT v.*, p.display_name AS subject_display_name,
       ew.workload_key AS expected_workload_key,
       aw.workload_key AS actual_workload_key,
       CASE WHEN r.id IS NULL THEN NULL ELSE lower(r.during) END AS scheduled_at
FROM request_read.service_queue_status_v2 v
LEFT JOIN request_engine.parties p
  ON p.organization_id = v.organization_id AND p.id = v.subject_party_id
LEFT JOIN request_engine.operational_workload_classifications ew
  ON ew.organization_id = v.organization_id AND ew.id = v.expected_workload_classification_id
LEFT JOIN request_engine.operational_workload_classifications aw
  ON aw.organization_id = v.organization_id AND aw.id = v.actual_workload_classification_id
LEFT JOIN request_engine.reservations r
  ON r.organization_id = v.organization_id AND r.id = v.reservation_id;

REVOKE ALL ON request_engine.operational_workload_classifications,
  request_engine.service_sessions, request_engine.service_session_interruptions,
  request_engine.resource_activities FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE ON request_engine.operational_workload_classifications,
  request_engine.service_sessions, request_engine.service_session_interruptions,
  request_engine.resource_activities TO request_engine_app;
GRANT SELECT ON request_read.service_queue_status_v2,
  request_read.service_session_status_v1, request_read.live_service_staff_v1
  TO request_engine_app, request_engine_admin;
GRANT ALL PRIVILEGES ON request_engine.operational_workload_classifications,
  request_engine.service_sessions, request_engine.service_session_interruptions,
  request_engine.resource_activities TO request_engine_admin;

RESET ROLE;
RESET search_path;
"""


def upgrade() -> None:
    op.execute(_SQL)


def downgrade() -> None:
    raise RuntimeError(
        "0005 introduces authoritative F3 execution history and is not reversible in place"
    )
