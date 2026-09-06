"""Consolidate duplicate direct Queue recovery freshness triggers.

Revision ID: 0049_consolidate_recovery_bump
Revises: 0048_remove_legacy_location
Create Date: 2026-09-06
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0049_consolidate_recovery_bump"
down_revision: str | Sequence[str] | None = "0048_remove_legacy_location"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SQL = r"""
SET ROLE request_engine_schema_owner;

CREATE FUNCTION request_engine.bump_direct_queue_recovery_source_revision()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
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

REVOKE ALL ON FUNCTION request_engine.bump_direct_queue_recovery_source_revision()
FROM PUBLIC;

DROP TRIGGER queue_entries_bump_recovery_source_revision
ON request_engine.queue_entries;
CREATE TRIGGER queue_entries_bump_recovery_source_revision
AFTER INSERT OR UPDATE OR DELETE ON request_engine.queue_entries
FOR EACH ROW
EXECUTE FUNCTION request_engine.bump_direct_queue_recovery_source_revision();

DROP TRIGGER live_capacity_projection_policies_bump_recovery_source_revision
ON request_engine.live_capacity_projection_policies;
CREATE TRIGGER live_capacity_projection_policies_bump_recovery_source_revision
AFTER INSERT OR UPDATE OR DELETE ON request_engine.live_capacity_projection_policies
FOR EACH ROW
EXECUTE FUNCTION request_engine.bump_direct_queue_recovery_source_revision();

DROP FUNCTION request_engine.bump_queue_recovery_source_revision();
DROP FUNCTION request_engine.bump_projection_policy_recovery_source_revision();

RESET ROLE;
"""


def upgrade() -> None:
    op.execute(_SQL)


def downgrade() -> None:
    raise RuntimeError("pre-launch recovery trigger consolidation is not reversible")
