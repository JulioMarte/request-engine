"""Harden F3 live-service invariants before migration consolidation.

Revision ID: 0007_f3_live_hardening
Revises: 0006_f3_arrival_default
Create Date: 2026-08-25
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007_f3_live_hardening"
down_revision: str | Sequence[str] | None = "0006_f3_arrival_default"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SQL = r"""
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, request_read, pg_catalog;

CREATE OR REPLACE FUNCTION request_engine.guard_live_resource_occupation()
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

CREATE OR REPLACE FUNCTION request_engine.assert_service_queue_coherence()
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

CREATE OR REPLACE FUNCTION request_engine.assert_session_interruption_coherence()
RETURNS trigger LANGUAGE plpgsql AS $function$
DECLARE
    v_session_id uuid;
    v_status text;
    v_open bigint;
BEGIN
    IF TG_TABLE_NAME = 'service_sessions' THEN
        v_session_id := NEW.id;
    ELSE
        v_session_id := NEW.service_session_id;
    END IF;
    SELECT status INTO v_status FROM request_engine.service_sessions
     WHERE organization_id = NEW.organization_id AND id = v_session_id;
    IF NOT FOUND THEN RETURN NEW; END IF;
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

RESET ROLE;
RESET search_path;
"""


def upgrade() -> None:
    op.execute(_SQL)


def downgrade() -> None:
    raise RuntimeError("0007 hardens authoritative F3 invariants and is not reversible")
