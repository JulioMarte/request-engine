"""Harden F3 workload vocabulary lifecycle.

Revision ID: 0006_f3_acceptance
Revises: 0005_live_service_ops
Create Date: 2026-08-25
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006_f3_acceptance"
down_revision: str | Sequence[str] | None = "0005_live_service_ops"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SQL = r"""
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, request_read, pg_catalog;

ALTER TABLE request_engine.operational_workload_classifications
    ADD CONSTRAINT operational_workload_key_trimmed_ck
      CHECK (workload_key = btrim(workload_key)),
    ADD CONSTRAINT operational_workload_display_name_trimmed_ck
      CHECK (display_name = btrim(display_name));

CREATE FUNCTION request_engine.guard_operational_workload_classification()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'OperationalWorkloadClassification is append-preserving; deactivate it'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.organization_id IS DISTINCT FROM NEW.organization_id
       OR OLD.id IS DISTINCT FROM NEW.id
       OR OLD.workload_key IS DISTINCT FROM NEW.workload_key THEN
        RAISE EXCEPTION 'OperationalWorkloadClassification identity cannot be retargeted'
            USING ERRCODE = '23514';
    END IF;
    IF NOT OLD.active AND NEW IS DISTINCT FROM OLD THEN
        RAISE EXCEPTION 'inactive OperationalWorkloadClassification is immutable'
            USING ERRCODE = '23514';
    END IF;
    IF NEW IS DISTINCT FROM OLD AND NEW.revision <> OLD.revision + 1 THEN
        RAISE EXCEPTION 'OperationalWorkloadClassification revision must advance exactly one step'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$;

CREATE TRIGGER operational_workload_classifications_guard_transition
BEFORE UPDATE OR DELETE ON request_engine.operational_workload_classifications
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_operational_workload_classification();

RESET ROLE;
RESET search_path;
"""


def upgrade() -> None:
    op.execute(_SQL)


def downgrade() -> None:
    raise RuntimeError(
        "0006 hardens authoritative F3 workload history and is not reversible in place"
    )
