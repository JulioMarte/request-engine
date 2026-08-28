"""Schedule F5 reassessment with each authoritative freshness revision.

Revision ID: 0013_f5_scheduled_reassessment
Revises: 0012_f5_schedule_freshness
Create Date: 2026-08-28
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0013_f5_scheduled_reassessment"
down_revision: str | Sequence[str] | None = "0012_f5_schedule_freshness"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SQL = r"""
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, pg_catalog;

CREATE OR REPLACE FUNCTION request_engine.bump_recovery_source_revision(
    p_organization_id uuid,
    p_service_queue_id uuid
) RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = request_engine, pg_catalog
AS $function$
DECLARE
    v_revision bigint;
    v_now timestamptz := clock_timestamp();
    v_dedupe_key text;
BEGIN
    IF p_service_queue_id IS NULL THEN
        RETURN;
    END IF;

    PERFORM set_config(
        'request_engine.organization_id',
        p_organization_id::text,
        true
    );

    INSERT INTO request_engine.recovery_source_revisions (
        organization_id, service_queue_id, revision, updated_at
    ) VALUES (
        p_organization_id, p_service_queue_id, 1, v_now
    )
    ON CONFLICT (organization_id, service_queue_id)
    DO UPDATE SET
        revision = request_engine.recovery_source_revisions.revision + 1,
        updated_at = v_now
    RETURNING revision INTO v_revision;

    v_dedupe_key := format(
        'f5-reassessment:%s:%s',
        p_service_queue_id,
        v_revision
    );
    INSERT INTO request_engine.scheduled_actions (
        organization_id,
        owner_module,
        action_type,
        action_version,
        subject_kind,
        subject_id,
        payload,
        dedupe_key,
        execute_at,
        next_attempt_at,
        max_attempts
    ) VALUES (
        p_organization_id,
        'operational_recovery',
        'reassess_recovery_scope',
        1,
        'ServiceQueue',
        p_service_queue_id,
        jsonb_build_object(
            'service_queue_id', p_service_queue_id::text,
            'source_revision', v_revision
        ),
        v_dedupe_key,
        v_now,
        v_now,
        8
    )
    ON CONFLICT (organization_id, dedupe_key) DO NOTHING;
END
$function$;
REVOKE ALL ON FUNCTION request_engine.bump_recovery_source_revision(uuid, uuid) FROM PUBLIC;

RESET ROLE;
RESET search_path;
"""


def upgrade() -> None:
    op.execute(_SQL)


def downgrade() -> None:
    raise RuntimeError("0013 adds durable F5 reassessment and is not reversible in place")
