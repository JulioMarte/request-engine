"""Harden F3 historical execution facts.

Revision ID: 0006_f3_fact_hardening
Revises: 0005_live_service_ops
Create Date: 2026-08-26
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006_f3_fact_hardening"
down_revision: str | Sequence[str] | None = "0005_live_service_ops"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SQL = r"""
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, request_read, pg_catalog;

ALTER TABLE request_engine.service_session_interruptions
    ADD CONSTRAINT service_session_interruptions_end_actor_ck
      CHECK ((ended_at IS NULL) = (ended_by_principal_id IS NULL));

CREATE FUNCTION request_engine.guard_service_session_interruption_transition()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'ServiceSessionInterruption is append-preserving'
            USING ERRCODE = '23514';
    END IF;

    IF OLD.organization_id IS DISTINCT FROM NEW.organization_id
       OR OLD.id IS DISTINCT FROM NEW.id
       OR OLD.service_session_id IS DISTINCT FROM NEW.service_session_id
       OR OLD.kind IS DISTINCT FROM NEW.kind
       OR OLD.started_at IS DISTINCT FROM NEW.started_at
       OR OLD.started_by_principal_id IS DISTINCT FROM NEW.started_by_principal_id
       OR OLD.created_at IS DISTINCT FROM NEW.created_at THEN
        RAISE EXCEPTION 'ServiceSessionInterruption historical identity is immutable'
            USING ERRCODE = '23514';
    END IF;

    IF OLD.ended_at IS NOT NULL AND NEW IS DISTINCT FROM OLD THEN
        RAISE EXCEPTION 'ended ServiceSessionInterruption is immutable'
            USING ERRCODE = '23514';
    END IF;

    IF OLD.ended_at IS NULL AND (
        NEW.ended_at IS NULL OR NEW.ended_by_principal_id IS NULL
    ) AND NEW IS DISTINCT FROM OLD THEN
        RAISE EXCEPTION
            'ServiceSessionInterruption may only transition atomically from open to ended'
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END
$function$;

CREATE TRIGGER service_session_interruptions_guard_transition
BEFORE UPDATE OR DELETE ON request_engine.service_session_interruptions
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_service_session_interruption_transition();

CREATE OR REPLACE FUNCTION request_engine.guard_service_session_transition()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    IF OLD.organization_id IS DISTINCT FROM NEW.organization_id
       OR OLD.queue_entry_id IS DISTINCT FROM NEW.queue_entry_id
       OR OLD.resource_id IS DISTINCT FROM NEW.resource_id
       OR OLD.location_id IS DISTINCT FROM NEW.location_id THEN
        RAISE EXCEPTION 'ServiceSession execution identity cannot be retargeted'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.status = 'completed' AND NEW IS DISTINCT FROM OLD THEN
        RAISE EXCEPTION 'completed ServiceSession is immutable'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.status <> OLD.status AND NOT (
        (OLD.status = 'active' AND NEW.status IN ('paused', 'completed')) OR
        (OLD.status = 'paused' AND NEW.status = 'active')
    ) THEN
        RAISE EXCEPTION 'invalid ServiceSession transition from % to %', OLD.status, NEW.status
            USING ERRCODE = '23514';
    END IF;
    IF NEW.revision <> OLD.revision + 1 AND NEW IS DISTINCT FROM OLD THEN
        RAISE EXCEPTION 'ServiceSession revision must advance exactly one step'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.started_at IS DISTINCT FROM OLD.started_at THEN
        RAISE EXCEPTION 'ServiceSession started_at is immutable'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$;

RESET ROLE;
RESET search_path;
"""


def upgrade() -> None:
    op.execute(_SQL)


def downgrade() -> None:
    raise RuntimeError(
        "0006 strengthens authoritative F3 historical facts and is not reversible in place"
    )
