"""Encapsulate Delivery-to-Queue lifecycle transitions behind request_cmd.

Revision ID: 0043_queue_delivery_boundary
Revises: 0042_recovery_fence_boundary
Create Date: 2026-09-05
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0043_queue_delivery_boundary"
down_revision: str | Sequence[str] | None = "0042_recovery_fence_boundary"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET ROLE request_engine_schema_owner")
    op.execute(
        """
        CREATE FUNCTION request_cmd.mark_queue_entry_service_started(
            p_organization_id uuid,
            p_queue_entry_id uuid,
            p_started_at timestamptz
        ) RETURNS void
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, request_engine, pg_temp
        AS $function$
        BEGIN
            IF request_engine.current_organization_id() IS DISTINCT FROM p_organization_id THEN
                RAISE EXCEPTION 'queue service-start transition rejects foreign tenant authority'
                    USING ERRCODE = '23514';
            END IF;

            UPDATE request_engine.queue_entries
               SET status = 'serving',
                   service_started_at = p_started_at,
                   completed_at = NULL,
                   revision = revision + 1,
                   updated_at = clock_timestamp()
             WHERE organization_id = p_organization_id
               AND id = p_queue_entry_id
               AND status = 'called';

            IF NOT FOUND THEN
                RAISE EXCEPTION 'QueueEntry % is not callable', p_queue_entry_id
                    USING ERRCODE = '23514';
            END IF;
        END
        $function$;

        CREATE FUNCTION request_cmd.mark_queue_entry_service_completed(
            p_organization_id uuid,
            p_queue_entry_id uuid,
            p_completed_at timestamptz
        ) RETURNS void
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, request_engine, pg_temp
        AS $function$
        BEGIN
            IF request_engine.current_organization_id() IS DISTINCT FROM p_organization_id THEN
                RAISE EXCEPTION 'queue service-complete transition rejects foreign tenant authority'
                    USING ERRCODE = '23514';
            END IF;

            UPDATE request_engine.queue_entries
               SET status = 'completed',
                   completed_at = p_completed_at,
                   revision = revision + 1,
                   updated_at = clock_timestamp()
             WHERE organization_id = p_organization_id
               AND id = p_queue_entry_id
               AND status = 'serving';

            IF NOT FOUND THEN
                RAISE EXCEPTION 'QueueEntry % is not serving', p_queue_entry_id
                    USING ERRCODE = '23514';
            END IF;
        END
        $function$;

        REVOKE ALL ON FUNCTION request_cmd.mark_queue_entry_service_started(
            uuid, uuid, timestamptz
        ) FROM PUBLIC;
        REVOKE ALL ON FUNCTION request_cmd.mark_queue_entry_service_completed(
            uuid, uuid, timestamptz
        ) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_cmd.mark_queue_entry_service_started(
            uuid, uuid, timestamptz
        ) TO request_engine_app;
        GRANT EXECUTE ON FUNCTION request_cmd.mark_queue_entry_service_completed(
            uuid, uuid, timestamptz
        ) TO request_engine_app;
        """
    )
    op.execute("RESET ROLE")


def downgrade() -> None:
    raise RuntimeError("Queue/Delivery boundary hardening is not reversible")
