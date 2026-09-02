"""Fix F7e queue-reference trigger row-shape handling.

Revision ID: 0029_f7e_queue_ref_fix
Revises: 0028_f7e_same_day_selection
Create Date: 2026-09-02
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0029_f7e_queue_ref_fix"
down_revision: str | Sequence[str] | None = "0028_f7e_same_day_selection"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SQL = r"""
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, request_read, request_cmd, pg_catalog;

CREATE OR REPLACE FUNCTION request_engine.assert_f7e_queue_reference()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
DECLARE
    v_target_queue_id uuid;
    v_target_status text;
    v_called_queue_id uuid;
    v_called_status text;
BEGIN
    SELECT service_queue_id, status INTO v_target_queue_id, v_target_status
      FROM request_engine.queue_entries
     WHERE organization_id = NEW.organization_id
       AND id = NEW.queue_entry_id;
    IF v_target_queue_id IS NULL OR v_target_queue_id <> NEW.service_queue_id THEN
        RAISE EXCEPTION 'F7e QueueEntry must belong to referenced ServiceQueue'
            USING ERRCODE = '23514';
    END IF;

    IF TG_TABLE_NAME = 'queue_recall_holds' THEN
        IF v_target_status <> 'waiting' THEN
            RAISE EXCEPTION 'recall hold requires a waiting QueueEntry'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;

    IF TG_TABLE_NAME = 'queue_selection_facts' THEN
        IF NEW.selection_kind = 'skip' AND v_target_status <> 'waiting' THEN
            RAISE EXCEPTION 'skip fact requires the skipped QueueEntry to remain waiting'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.selection_kind = 'operator_select' AND v_target_status <> 'called' THEN
            RAISE EXCEPTION 'operator selection fact requires a called QueueEntry'
                USING ERRCODE = '23514';
        END IF;

        IF NEW.called_queue_entry_id IS NOT NULL THEN
            SELECT service_queue_id, status INTO v_called_queue_id, v_called_status
              FROM request_engine.queue_entries
             WHERE organization_id = NEW.organization_id
               AND id = NEW.called_queue_entry_id;
            IF v_called_queue_id IS NULL OR v_called_queue_id <> NEW.service_queue_id THEN
                RAISE EXCEPTION 'F7e called QueueEntry must belong to referenced ServiceQueue'
                    USING ERRCODE = '23514';
            END IF;
            IF v_called_status <> 'called' THEN
                RAISE EXCEPTION 'F7e called QueueEntry must be in called state'
                    USING ERRCODE = '23514';
            END IF;
        END IF;
        RETURN NEW;
    END IF;

    RAISE EXCEPTION 'unsupported table for F7e queue reference trigger: %', TG_TABLE_NAME
        USING ERRCODE = '23514';
END
$function$;

REVOKE EXECUTE ON FUNCTION request_engine.assert_f7e_queue_reference() FROM PUBLIC;

RESET ROLE;
RESET search_path;
"""


def upgrade() -> None:
    op.execute(_SQL)


def downgrade() -> None:
    raise RuntimeError("0029 fixes F7e queue-reference trigger row-shape handling")
