"""Initialize omitted F3 queue times from one PostgreSQL clock read.

Revision ID: 0006_f3_queue_time_init
Revises: 0005_live_service_ops
Create Date: 2026-08-25
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006_f3_queue_time_init"
down_revision: str | Sequence[str] | None = "0005_live_service_ops"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SQL = r"""
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, request_read, pg_catalog;

ALTER TABLE request_engine.queue_entries
    ALTER COLUMN arrived_at DROP DEFAULT,
    ALTER COLUMN admitted_at DROP DEFAULT;

CREATE FUNCTION request_engine.initialize_queue_entry_times()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
DECLARE
    v_now timestamptz;
BEGIN
    IF NEW.arrived_at IS NULL AND NEW.admitted_at IS NULL THEN
        v_now := clock_timestamp();
        NEW.arrived_at := v_now;
        NEW.admitted_at := v_now;
    ELSIF NEW.arrived_at IS NULL THEN
        NEW.arrived_at := NEW.admitted_at;
    ELSIF NEW.admitted_at IS NULL THEN
        NEW.admitted_at := NEW.arrived_at;
    END IF;
    RETURN NEW;
END
$function$;

CREATE TRIGGER queue_entries_initialize_times
BEFORE INSERT ON request_engine.queue_entries
FOR EACH ROW EXECUTE FUNCTION request_engine.initialize_queue_entry_times();

RESET ROLE;
RESET search_path;
"""


def upgrade() -> None:
    op.execute(_SQL)


def downgrade() -> None:
    raise RuntimeError("F3 feature migrations are forward-only before merge consolidation")
