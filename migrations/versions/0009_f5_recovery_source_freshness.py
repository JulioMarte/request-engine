"""Add F5 recovery source freshness serialization.

Revision ID: 0009_f5_source_freshness
Revises: 0008_operational_recovery
Create Date: 2026-08-27
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009_f5_source_freshness"
down_revision: str | Sequence[str] | None = "0008_operational_recovery"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SQL = r"""
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, request_read, request_cmd, pg_catalog;

CREATE TABLE request_engine.recovery_source_revisions (
    organization_id uuid NOT NULL REFERENCES request_engine.organizations(id),
    service_queue_id uuid NOT NULL,
    revision bigint NOT NULL DEFAULT 1,
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (organization_id, service_queue_id),
    FOREIGN KEY (organization_id, service_queue_id)
      REFERENCES request_engine.service_queues (organization_id, id),
    CHECK (revision > 0)
);

INSERT INTO request_engine.recovery_source_revisions (organization_id, service_queue_id)
SELECT organization_id, service_queue_id
FROM request_engine.live_capacity_projection_policies
ON CONFLICT (organization_id, service_queue_id) DO NOTHING;

ALTER TABLE request_engine.recovery_source_revisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE request_engine.recovery_source_revisions FORCE ROW LEVEL SECURITY;
CREATE POLICY recovery_source_revisions_tenant_policy
  ON request_engine.recovery_source_revisions
  USING (organization_id = request_engine.current_organization_id())
  WITH CHECK (organization_id = request_engine.current_organization_id());

REVOKE ALL ON request_engine.recovery_source_revisions FROM PUBLIC;
GRANT SELECT ON request_engine.recovery_source_revisions TO request_engine_app;
GRANT ALL PRIVILEGES ON request_engine.recovery_source_revisions TO request_engine_admin;

CREATE FUNCTION request_engine.bump_recovery_source_revision(
    p_organization_id uuid,
    p_service_queue_id uuid
) RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = request_engine, pg_catalog
AS $function$
BEGIN
    IF p_service_queue_id IS NULL THEN
        RETURN;
    END IF;
    INSERT INTO request_engine.recovery_source_revisions (
        organization_id, service_queue_id, revision, updated_at
    ) VALUES (
        p_organization_id, p_service_queue_id, 1, clock_timestamp()
    )
    ON CONFLICT (organization_id, service_queue_id)
    DO UPDATE SET
        revision = request_engine.recovery_source_revisions.revision + 1,
        updated_at = clock_timestamp();
END
$function$;
REVOKE ALL ON FUNCTION request_engine.bump_recovery_source_revision(uuid, uuid) FROM PUBLIC;

CREATE FUNCTION request_engine.bump_queue_recovery_source_revision()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = request_engine, pg_catalog
AS $function$
BEGIN
    IF TG_OP = 'DELETE' THEN
        PERFORM request_engine.bump_recovery_source_revision(
            OLD.organization_id,
            OLD.service_queue_id
        );
        RETURN OLD;
    END IF;
    IF TG_OP = 'UPDATE'
       AND (OLD.organization_id, OLD.service_queue_id)
           IS DISTINCT FROM (NEW.organization_id, NEW.service_queue_id) THEN
        PERFORM request_engine.bump_recovery_source_revision(
            OLD.organization_id,
            OLD.service_queue_id
        );
    END IF;
    PERFORM request_engine.bump_recovery_source_revision(
        NEW.organization_id,
        NEW.service_queue_id
    );
    RETURN NEW;
END
$function$;

CREATE TRIGGER queue_entries_bump_recovery_source_revision
AFTER INSERT OR UPDATE OR DELETE ON request_engine.queue_entries
FOR EACH ROW EXECUTE FUNCTION request_engine.bump_queue_recovery_source_revision();

CREATE FUNCTION request_engine.bump_service_session_recovery_source_revision()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = request_engine, pg_catalog
AS $function$
DECLARE
    v_organization_id uuid;
    v_queue_entry_id uuid;
    v_queue_id uuid;
BEGIN
    IF TG_OP = 'DELETE' THEN
        v_organization_id := OLD.organization_id;
        v_queue_entry_id := OLD.queue_entry_id;
    ELSE
        v_organization_id := NEW.organization_id;
        v_queue_entry_id := NEW.queue_entry_id;
    END IF;
    SELECT service_queue_id INTO v_queue_id
    FROM request_engine.queue_entries
    WHERE organization_id = v_organization_id AND id = v_queue_entry_id;
    PERFORM request_engine.bump_recovery_source_revision(v_organization_id, v_queue_id);
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END
$function$;

CREATE TRIGGER service_sessions_bump_recovery_source_revision
AFTER INSERT OR UPDATE OR DELETE ON request_engine.service_sessions
FOR EACH ROW EXECUTE FUNCTION request_engine.bump_service_session_recovery_source_revision();

CREATE FUNCTION request_engine.bump_interruption_recovery_source_revision()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = request_engine, pg_catalog
AS $function$
DECLARE
    v_organization_id uuid;
    v_session_id uuid;
    v_queue_id uuid;
BEGIN
    IF TG_OP = 'DELETE' THEN
        v_organization_id := OLD.organization_id;
        v_session_id := OLD.service_session_id;
    ELSE
        v_organization_id := NEW.organization_id;
        v_session_id := NEW.service_session_id;
    END IF;
    SELECT q.service_queue_id INTO v_queue_id
    FROM request_engine.service_sessions s
    JOIN request_engine.queue_entries q
      ON q.organization_id = s.organization_id AND q.id = s.queue_entry_id
    WHERE s.organization_id = v_organization_id AND s.id = v_session_id;
    PERFORM request_engine.bump_recovery_source_revision(v_organization_id, v_queue_id);
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END
$function$;

CREATE TRIGGER service_session_interruptions_bump_recovery_source_revision
AFTER INSERT OR UPDATE OR DELETE ON request_engine.service_session_interruptions
FOR EACH ROW EXECUTE FUNCTION request_engine.bump_interruption_recovery_source_revision();

CREATE FUNCTION request_engine.bump_resource_activity_recovery_source_revision()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = request_engine, pg_catalog
AS $function$
DECLARE
    v_organization_id uuid;
    v_resource_id uuid;
    v_location_id uuid;
    v_queue_id uuid;
BEGIN
    IF TG_OP = 'DELETE' THEN
        v_organization_id := OLD.organization_id;
        v_resource_id := OLD.resource_id;
        v_location_id := OLD.location_id;
    ELSE
        v_organization_id := NEW.organization_id;
        v_resource_id := NEW.resource_id;
        v_location_id := NEW.location_id;
    END IF;
    FOR v_queue_id IN
        SELECT service_queue_id
        FROM request_engine.live_capacity_projection_policies
        WHERE organization_id = v_organization_id
          AND resource_id = v_resource_id
          AND (v_location_id IS NULL OR location_id = v_location_id)
    LOOP
        PERFORM request_engine.bump_recovery_source_revision(v_organization_id, v_queue_id);
    END LOOP;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END
$function$;

CREATE TRIGGER resource_activities_bump_recovery_source_revision
AFTER INSERT OR UPDATE OR DELETE ON request_engine.resource_activities
FOR EACH ROW EXECUTE FUNCTION request_engine.bump_resource_activity_recovery_source_revision();

CREATE FUNCTION request_engine.bump_projection_policy_recovery_source_revision()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = request_engine, pg_catalog
AS $function$
BEGIN
    IF TG_OP = 'DELETE' THEN
        PERFORM request_engine.bump_recovery_source_revision(
            OLD.organization_id,
            OLD.service_queue_id
        );
        RETURN OLD;
    END IF;
    IF TG_OP = 'UPDATE'
       AND (OLD.organization_id, OLD.service_queue_id)
           IS DISTINCT FROM (NEW.organization_id, NEW.service_queue_id) THEN
        PERFORM request_engine.bump_recovery_source_revision(
            OLD.organization_id,
            OLD.service_queue_id
        );
    END IF;
    PERFORM request_engine.bump_recovery_source_revision(
        NEW.organization_id,
        NEW.service_queue_id
    );
    RETURN NEW;
END
$function$;

CREATE TRIGGER live_capacity_projection_policies_bump_recovery_source_revision
AFTER INSERT OR UPDATE OR DELETE ON request_engine.live_capacity_projection_policies
FOR EACH ROW EXECUTE FUNCTION request_engine.bump_projection_policy_recovery_source_revision();

CREATE FUNCTION request_engine.bump_estimate_policy_recovery_source_revision()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = request_engine, pg_catalog
AS $function$
DECLARE
    v_organization_id uuid;
    v_queue_id uuid;
BEGIN
    IF TG_OP = 'DELETE' THEN
        v_organization_id := OLD.organization_id;
    ELSE
        v_organization_id := NEW.organization_id;
    END IF;
    FOR v_queue_id IN
        SELECT service_queue_id
        FROM request_engine.live_capacity_projection_policies
        WHERE organization_id = v_organization_id
    LOOP
        PERFORM request_engine.bump_recovery_source_revision(v_organization_id, v_queue_id);
    END LOOP;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END
$function$;

CREATE TRIGGER live_capacity_workload_estimate_policies_bump_recovery_source_revision
AFTER INSERT OR UPDATE OR DELETE ON request_engine.live_capacity_workload_estimate_policies
FOR EACH ROW EXECUTE FUNCTION request_engine.bump_estimate_policy_recovery_source_revision();

CREATE FUNCTION request_read.recovery_source_revision(
    p_organization_id uuid,
    p_service_queue_id uuid
) RETURNS bigint
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = request_engine, pg_catalog
AS $function$
    SELECT revision
    FROM request_engine.recovery_source_revisions
    WHERE organization_id = p_organization_id
      AND service_queue_id = p_service_queue_id
$function$;
REVOKE ALL ON FUNCTION request_read.recovery_source_revision(uuid, uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION request_read.recovery_source_revision(uuid, uuid)
  TO request_engine_app, request_engine_admin;

CREATE FUNCTION request_cmd.lock_recovery_source_revision(
    p_organization_id uuid,
    p_service_queue_id uuid
) RETURNS bigint
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = request_engine, pg_catalog
AS $function$
DECLARE
    v_revision bigint;
BEGIN
    SELECT revision INTO v_revision
    FROM request_engine.recovery_source_revisions
    WHERE organization_id = p_organization_id
      AND service_queue_id = p_service_queue_id
    FOR UPDATE;
    IF v_revision IS NULL THEN
        RAISE EXCEPTION 'Recovery source revision is not configured for queue %',
            p_service_queue_id
          USING ERRCODE = '23514';
    END IF;
    RETURN v_revision;
END
$function$;
REVOKE ALL ON FUNCTION request_cmd.lock_recovery_source_revision(uuid, uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION request_cmd.lock_recovery_source_revision(uuid, uuid)
  TO request_engine_app, request_engine_admin;

RESET ROLE;
RESET search_path;
"""


def upgrade() -> None:
    op.execute(_SQL)


def downgrade() -> None:
    raise RuntimeError("0009 introduces durable F5 freshness guards and is not reversible in place")
