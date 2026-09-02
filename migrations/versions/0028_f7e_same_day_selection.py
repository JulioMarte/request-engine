"""Add F7e same-day selection facts and recall holds.

Revision ID: 0028_f7e_same_day_selection
Revises: 0027_f7_operator_day_board
Create Date: 2026-09-02
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0028_f7e_same_day_selection"
down_revision: str | Sequence[str] | None = "0027_f7_operator_day_board"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SQL = r"""
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, request_read, request_cmd, pg_catalog;

CREATE TABLE request_engine.queue_recall_holds (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL,
    service_queue_id uuid NOT NULL,
    queue_entry_id uuid NOT NULL,
    hold_kind text NOT NULL,
    release_at timestamptz,
    reason text,
    created_by_principal_id uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    released_at timestamptz,
    released_by_principal_id uuid,
    release_reason text,
    UNIQUE (organization_id, id),
    FOREIGN KEY (organization_id, service_queue_id)
        REFERENCES request_engine.service_queues (organization_id, id),
    FOREIGN KEY (organization_id, queue_entry_id)
        REFERENCES request_engine.queue_entries (organization_id, id),
    FOREIGN KEY (organization_id, created_by_principal_id)
        REFERENCES request_engine.principals (organization_id, id),
    FOREIGN KEY (organization_id, released_by_principal_id)
        REFERENCES request_engine.principals (organization_id, id),
    CHECK (hold_kind IN ('until_time', 'until_customer_initiates')),
    CHECK (
        (hold_kind = 'until_time' AND release_at IS NOT NULL)
        OR (hold_kind = 'until_customer_initiates' AND release_at IS NULL)
    ),
    CHECK (reason IS NULL OR char_length(reason) <= 500),
    CHECK (release_reason IS NULL OR char_length(release_reason) <= 120),
    CHECK (released_at IS NULL OR released_at >= created_at),
    CHECK (
        (released_at IS NULL AND released_by_principal_id IS NULL AND release_reason IS NULL)
        OR (released_at IS NOT NULL AND released_by_principal_id IS NOT NULL
            AND release_reason IS NOT NULL)
    )
);

CREATE UNIQUE INDEX queue_recall_holds_one_current_uq
    ON request_engine.queue_recall_holds (organization_id, queue_entry_id)
    WHERE released_at IS NULL;
CREATE INDEX queue_recall_holds_queue_gate_idx
    ON request_engine.queue_recall_holds
       (organization_id, service_queue_id, queue_entry_id, released_at, release_at);

CREATE TABLE request_engine.queue_selection_facts (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL,
    service_queue_id uuid NOT NULL,
    queue_entry_id uuid NOT NULL,
    selection_kind text NOT NULL,
    reason text NOT NULL,
    selected_by_principal_id uuid NOT NULL,
    selected_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    called_queue_entry_id uuid,
    UNIQUE (organization_id, id),
    FOREIGN KEY (organization_id, service_queue_id)
        REFERENCES request_engine.service_queues (organization_id, id),
    FOREIGN KEY (organization_id, queue_entry_id)
        REFERENCES request_engine.queue_entries (organization_id, id),
    FOREIGN KEY (organization_id, called_queue_entry_id)
        REFERENCES request_engine.queue_entries (organization_id, id),
    FOREIGN KEY (organization_id, selected_by_principal_id)
        REFERENCES request_engine.principals (organization_id, id),
    CHECK (selection_kind IN ('operator_select', 'skip')),
    CHECK (
        (selection_kind = 'operator_select'
         AND reason IN ('urgent_operational_need', 'booked_time_due', 'operator_override')
         AND called_queue_entry_id IS NULL)
        OR
        (selection_kind = 'skip'
         AND reason IN ('temporarily_unavailable', 'no_response', 'operator_override'))
    )
);

CREATE INDEX queue_selection_facts_history_idx
    ON request_engine.queue_selection_facts
       (organization_id, service_queue_id, selected_at, id);
CREATE INDEX queue_selection_facts_entry_idx
    ON request_engine.queue_selection_facts
       (organization_id, queue_entry_id, selected_at, id);

CREATE FUNCTION request_engine.assert_f7e_queue_reference()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
DECLARE
    v_target_queue_id uuid;
    v_called_queue_id uuid;
BEGIN
    SELECT service_queue_id INTO v_target_queue_id
      FROM request_engine.queue_entries
     WHERE organization_id = NEW.organization_id
       AND id = NEW.queue_entry_id;
    IF v_target_queue_id IS NULL OR v_target_queue_id <> NEW.service_queue_id THEN
        RAISE EXCEPTION 'F7e QueueEntry must belong to referenced ServiceQueue'
            USING ERRCODE = '23514';
    END IF;

    IF TG_TABLE_NAME = 'queue_selection_facts'
       AND NEW.called_queue_entry_id IS NOT NULL THEN
        SELECT service_queue_id INTO v_called_queue_id
          FROM request_engine.queue_entries
         WHERE organization_id = NEW.organization_id
           AND id = NEW.called_queue_entry_id;
        IF v_called_queue_id IS NULL OR v_called_queue_id <> NEW.service_queue_id THEN
            RAISE EXCEPTION 'F7e called QueueEntry must belong to referenced ServiceQueue'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END
$function$;

CREATE TRIGGER queue_recall_holds_assert_queue_reference
BEFORE INSERT ON request_engine.queue_recall_holds
FOR EACH ROW EXECUTE FUNCTION request_engine.assert_f7e_queue_reference();
CREATE TRIGGER queue_selection_facts_assert_queue_reference
BEFORE INSERT ON request_engine.queue_selection_facts
FOR EACH ROW EXECUTE FUNCTION request_engine.assert_f7e_queue_reference();

CREATE FUNCTION request_engine.guard_queue_recall_hold()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'queue recall hold history is append-preserving'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.organization_id IS DISTINCT FROM NEW.organization_id
       OR OLD.id IS DISTINCT FROM NEW.id
       OR OLD.service_queue_id IS DISTINCT FROM NEW.service_queue_id
       OR OLD.queue_entry_id IS DISTINCT FROM NEW.queue_entry_id
       OR OLD.hold_kind IS DISTINCT FROM NEW.hold_kind
       OR OLD.release_at IS DISTINCT FROM NEW.release_at
       OR OLD.reason IS DISTINCT FROM NEW.reason
       OR OLD.created_by_principal_id IS DISTINCT FROM NEW.created_by_principal_id
       OR OLD.created_at IS DISTINCT FROM NEW.created_at THEN
        RAISE EXCEPTION 'queue recall hold fact identity is immutable'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.released_at IS NOT NULL
       AND (NEW.released_at IS DISTINCT FROM OLD.released_at
            OR NEW.released_by_principal_id IS DISTINCT FROM OLD.released_by_principal_id
            OR NEW.release_reason IS DISTINCT FROM OLD.release_reason) THEN
        RAISE EXCEPTION 'released queue recall hold is immutable'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.released_at IS NULL AND NEW.released_at IS NULL
       AND (NEW.released_by_principal_id IS DISTINCT FROM OLD.released_by_principal_id
            OR NEW.release_reason IS DISTINCT FROM OLD.release_reason) THEN
        RAISE EXCEPTION 'queue recall hold release metadata requires release transition'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$;
CREATE TRIGGER queue_recall_holds_guard_transition
BEFORE UPDATE OR DELETE ON request_engine.queue_recall_holds
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_queue_recall_hold();

CREATE FUNCTION request_engine.guard_queue_selection_fact()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    RAISE EXCEPTION 'queue selection facts are immutable'
        USING ERRCODE = '23514';
END
$function$;
CREATE TRIGGER queue_selection_facts_guard_immutable
BEFORE UPDATE OR DELETE ON request_engine.queue_selection_facts
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_queue_selection_fact();

REVOKE EXECUTE ON FUNCTION request_engine.assert_f7e_queue_reference() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION request_engine.guard_queue_recall_hold() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION request_engine.guard_queue_selection_fact() FROM PUBLIC;

ALTER TABLE request_engine.queue_recall_holds ENABLE ROW LEVEL SECURITY;
ALTER TABLE request_engine.queue_recall_holds FORCE ROW LEVEL SECURITY;
CREATE POLICY queue_recall_holds_tenant_policy
  ON request_engine.queue_recall_holds
  USING (organization_id = request_engine.current_organization_id())
  WITH CHECK (organization_id = request_engine.current_organization_id());

ALTER TABLE request_engine.queue_selection_facts ENABLE ROW LEVEL SECURITY;
ALTER TABLE request_engine.queue_selection_facts FORCE ROW LEVEL SECURITY;
CREATE POLICY queue_selection_facts_tenant_policy
  ON request_engine.queue_selection_facts
  USING (organization_id = request_engine.current_organization_id())
  WITH CHECK (organization_id = request_engine.current_organization_id());

REVOKE ALL ON request_engine.queue_recall_holds FROM PUBLIC;
REVOKE ALL ON request_engine.queue_selection_facts FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE ON request_engine.queue_recall_holds TO request_engine_app;
GRANT SELECT, INSERT ON request_engine.queue_selection_facts TO request_engine_app;
GRANT ALL PRIVILEGES ON request_engine.queue_recall_holds TO request_engine_admin;
GRANT ALL PRIVILEGES ON request_engine.queue_selection_facts TO request_engine_admin;

RESET ROLE;
RESET search_path;
"""


def upgrade() -> None:
    op.execute(_SQL)


def downgrade() -> None:
    raise RuntimeError("0028 adds F7e queue selection facts and recall holds and is not reversible")
