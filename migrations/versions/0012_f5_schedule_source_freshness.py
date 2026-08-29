"""Advance F5 freshness from authoritative owner availability revisions.

Revision ID: 0012_f5_schedule_freshness
Revises: 0011_f5_full_recovery
Create Date: 2026-08-28
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0012_f5_schedule_freshness"
down_revision: str | Sequence[str] | None = "0011_f5_full_recovery"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SQL = r"""
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, pg_catalog;

CREATE POLICY live_capacity_projection_policies_recovery_trigger_read
ON request_engine.live_capacity_projection_policies
FOR SELECT
TO request_engine_schema_owner
USING (pg_trigger_depth() > 0);

CREATE FUNCTION request_engine.bump_location_revision_recovery_sources()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = request_engine, pg_catalog
AS $function$
DECLARE
    v_queue_id uuid;
BEGIN
    IF NEW.operational_revision IS NOT DISTINCT FROM OLD.operational_revision THEN
        RETURN NEW;
    END IF;
    FOR v_queue_id IN
        SELECT service_queue_id
        FROM request_engine.live_capacity_projection_policies
        WHERE organization_id = NEW.organization_id
          AND location_id = NEW.id
    LOOP
        PERFORM request_engine.bump_recovery_source_revision(
            NEW.organization_id,
            v_queue_id
        );
    END LOOP;
    RETURN NEW;
END
$function$;
REVOKE ALL ON FUNCTION request_engine.bump_location_revision_recovery_sources() FROM PUBLIC;

CREATE TRIGGER locations_bump_recovery_source_revision
AFTER UPDATE OF operational_revision ON request_engine.locations
FOR EACH ROW EXECUTE FUNCTION request_engine.bump_location_revision_recovery_sources();

CREATE FUNCTION request_engine.bump_resource_revision_recovery_sources()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = request_engine, pg_catalog
AS $function$
DECLARE
    v_queue_id uuid;
BEGIN
    IF NEW.availability_revision IS NOT DISTINCT FROM OLD.availability_revision THEN
        RETURN NEW;
    END IF;
    FOR v_queue_id IN
        SELECT service_queue_id
        FROM request_engine.live_capacity_projection_policies
        WHERE organization_id = NEW.organization_id
          AND resource_id = NEW.id
    LOOP
        PERFORM request_engine.bump_recovery_source_revision(
            NEW.organization_id,
            v_queue_id
        );
    END LOOP;
    RETURN NEW;
END
$function$;
REVOKE ALL ON FUNCTION request_engine.bump_resource_revision_recovery_sources() FROM PUBLIC;

CREATE TRIGGER resources_bump_recovery_source_revision
AFTER UPDATE OF availability_revision ON request_engine.resources
FOR EACH ROW EXECUTE FUNCTION request_engine.bump_resource_revision_recovery_sources();

RESET ROLE;
RESET search_path;
"""


def upgrade() -> None:
    op.execute(_SQL)


def downgrade() -> None:
    raise RuntimeError("0012 extends authoritative F5 freshness and is not reversible in place")
