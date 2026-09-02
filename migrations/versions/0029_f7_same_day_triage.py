"""Add F7e same-day queue triage facts.

Revision ID: 0029_f7_same_day_triage
Revises: 0028_f7_operator_day_board
Create Date: 2026-09-02
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0029_f7_same_day_triage"
down_revision: str | Sequence[str] | None = "0028_f7_operator_day_board"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SQL = r"""
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, request_read, request_cmd, pg_catalog;

CREATE TABLE request_engine.queue_entry_recall_holds (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL,
    queue_entry_id uuid NOT NULL,
    condition_kind text NOT NULL,
    until_at timestamptz,
    event_key text,
    reason text,
    created_by_principal_id uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    released_at timestamptz,
    release_kind text,
    FOREIGN KEY (organization_id, queue_entry_id)
      REFERENCES request_engine.queue_entries (organization_id, id),
    FOREIGN KEY (organization_id, created_by_principal_id)
      REFERENCES request_engine.principals (organization_id, id),
    CHECK (condition_kind IN ('until_time','until_event','until_customer_initiates')),
    CHECK ((condition_kind = 'until_time') = (until_at IS NOT NULL)),
    CHECK ((condition_kind = 'until_event') = (event_key IS NOT NULL)),
    CHECK (event_key IS NULL OR event_key = 'external_step_completed'),
    CHECK (reason IS NULL OR (btrim(reason) <> '' AND length(reason) <= 250)),
    CHECK ((released_at IS NULL) = (release_kind IS NULL)),
    CHECK (release_kind IS NULL OR release_kind IN
      ('expired','operator_select','condition_satisfied'))
);
CREATE UNIQUE INDEX queue_entry_recall_holds_one_active_uq
  ON request_engine.queue_entry_recall_holds (organization_id, queue_entry_id)
  WHERE released_at IS NULL;

CREATE TABLE request_engine.queue_entry_skips (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL,
    queue_entry_id uuid NOT NULL,
    reason text NOT NULL,
    created_by_principal_id uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    consumed_at timestamptz,
    consumed_by_entry_id uuid,
    FOREIGN KEY (organization_id, queue_entry_id)
      REFERENCES request_engine.queue_entries (organization_id, id),
    FOREIGN KEY (organization_id, created_by_principal_id)
      REFERENCES request_engine.principals (organization_id, id),
    FOREIGN KEY (organization_id, consumed_by_entry_id)
      REFERENCES request_engine.queue_entries (organization_id, id),
    CHECK (reason IN ('temporarily_unavailable','no_response','operator_override')),
    CHECK ((consumed_at IS NULL) = (consumed_by_entry_id IS NULL))
);
CREATE UNIQUE INDEX queue_entry_skips_one_active_uq
  ON request_engine.queue_entry_skips (organization_id, queue_entry_id)
  WHERE consumed_at IS NULL;

CREATE TABLE request_engine.queue_entry_operator_selections (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL,
    queue_entry_id uuid NOT NULL,
    reason text NOT NULL,
    selected_by_principal_id uuid NOT NULL,
    selected_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (organization_id, queue_entry_id)
      REFERENCES request_engine.queue_entries (organization_id, id),
    FOREIGN KEY (organization_id, selected_by_principal_id)
      REFERENCES request_engine.principals (organization_id, id),
    CHECK (reason IN ('urgent','scheduled_commitment','operator_override'))
);

CREATE FUNCTION request_engine.guard_queue_entry_recall_hold()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'QueueEntry recall holds are append-preserving'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.organization_id IS DISTINCT FROM NEW.organization_id
       OR OLD.queue_entry_id IS DISTINCT FROM NEW.queue_entry_id
       OR OLD.condition_kind IS DISTINCT FROM NEW.condition_kind
       OR OLD.until_at IS DISTINCT FROM NEW.until_at
       OR OLD.event_key IS DISTINCT FROM NEW.event_key
       OR OLD.reason IS DISTINCT FROM NEW.reason
       OR OLD.created_by_principal_id IS DISTINCT FROM NEW.created_by_principal_id
       OR OLD.created_at IS DISTINCT FROM NEW.created_at THEN
        RAISE EXCEPTION 'QueueEntry recall hold facts are immutable'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.released_at IS NOT NULL AND NEW IS DISTINCT FROM OLD THEN
        RAISE EXCEPTION 'released QueueEntry recall hold is immutable'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$;
CREATE TRIGGER queue_entry_recall_holds_guard
BEFORE UPDATE OR DELETE ON request_engine.queue_entry_recall_holds
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_queue_entry_recall_hold();

CREATE FUNCTION request_engine.guard_queue_entry_skip()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'QueueEntry skips are append-preserving'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.organization_id IS DISTINCT FROM NEW.organization_id
       OR OLD.queue_entry_id IS DISTINCT FROM NEW.queue_entry_id
       OR OLD.reason IS DISTINCT FROM NEW.reason
       OR OLD.created_by_principal_id IS DISTINCT FROM NEW.created_by_principal_id
       OR OLD.created_at IS DISTINCT FROM NEW.created_at THEN
        RAISE EXCEPTION 'QueueEntry skip facts are immutable'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.consumed_at IS NOT NULL AND NEW IS DISTINCT FROM OLD THEN
        RAISE EXCEPTION 'consumed QueueEntry skip is immutable'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$;
CREATE TRIGGER queue_entry_skips_guard
BEFORE UPDATE OR DELETE ON request_engine.queue_entry_skips
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_queue_entry_skip();

CREATE FUNCTION request_engine.reject_queue_entry_operator_selection_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    RAISE EXCEPTION 'QueueEntry operator selections are immutable facts'
        USING ERRCODE = '23514';
END
$function$;
CREATE TRIGGER queue_entry_operator_selections_immutable
BEFORE UPDATE OR DELETE ON request_engine.queue_entry_operator_selections
FOR EACH ROW EXECUTE FUNCTION request_engine.reject_queue_entry_operator_selection_mutation();

ALTER TABLE request_engine.queue_entry_recall_holds ENABLE ROW LEVEL SECURITY;
ALTER TABLE request_engine.queue_entry_recall_holds FORCE ROW LEVEL SECURITY;
ALTER TABLE request_engine.queue_entry_skips ENABLE ROW LEVEL SECURITY;
ALTER TABLE request_engine.queue_entry_skips FORCE ROW LEVEL SECURITY;
ALTER TABLE request_engine.queue_entry_operator_selections ENABLE ROW LEVEL SECURITY;
ALTER TABLE request_engine.queue_entry_operator_selections FORCE ROW LEVEL SECURITY;
CREATE POLICY queue_entry_recall_holds_tenant ON request_engine.queue_entry_recall_holds
  USING (organization_id = request_engine.current_organization_id())
  WITH CHECK (organization_id = request_engine.current_organization_id());
CREATE POLICY queue_entry_skips_tenant ON request_engine.queue_entry_skips
  USING (organization_id = request_engine.current_organization_id())
  WITH CHECK (organization_id = request_engine.current_organization_id());
CREATE POLICY queue_entry_operator_selections_tenant
  ON request_engine.queue_entry_operator_selections
  USING (organization_id = request_engine.current_organization_id())
  WITH CHECK (organization_id = request_engine.current_organization_id());

REVOKE ALL ON request_engine.queue_entry_recall_holds,
  request_engine.queue_entry_skips,
  request_engine.queue_entry_operator_selections FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION request_engine.guard_queue_entry_recall_hold(),
  request_engine.guard_queue_entry_skip(),
  request_engine.reject_queue_entry_operator_selection_mutation() FROM PUBLIC;
GRANT SELECT, INSERT ON request_engine.queue_entry_recall_holds,
  request_engine.queue_entry_skips,
  request_engine.queue_entry_operator_selections TO request_engine_app;
GRANT UPDATE (released_at, release_kind)
  ON request_engine.queue_entry_recall_holds TO request_engine_app;
GRANT UPDATE (consumed_at, consumed_by_entry_id)
  ON request_engine.queue_entry_skips TO request_engine_app;
GRANT ALL PRIVILEGES ON request_engine.queue_entry_recall_holds,
  request_engine.queue_entry_skips,
  request_engine.queue_entry_operator_selections TO request_engine_admin;

RESET ROLE;
RESET search_path;
"""


def upgrade() -> None:
    op.execute(_SQL)


def downgrade() -> None:
    raise RuntimeError("0029 introduces authoritative queue triage facts")
