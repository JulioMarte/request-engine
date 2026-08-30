"""Add F5 change-storm coalescing via supersede-enqueue.

One shared enqueue primitive now owns the recovery reassessment wake-up:
``request_cmd.schedule_recovery_reassessment`` inserts the per-revision
deduped ScheduledAction and, in the same transaction, cancels older still
``pending`` reassessments of the same scope. The freshness bump trigger and
the bounded fallback sweep both enqueue through it, so trigger storms and
sweep repairs can never diverge in dedupe identity, ``execute_at`` semantics
or coalescing behavior. ``leased`` actions keep terminating through the
existing commit-fence freshness check; ``cancelled`` remains terminal and is
never resurrected by the sweep.

Revision ID: 0019_f5_change_storm_coalescing
Revises: 0018_f5_recovery_sweep_discovery
Create Date: 2026-08-29
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0019_f5_change_storm_coalescing"
down_revision: str | Sequence[str] | None = "0018_f5_recovery_sweep_discovery"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEDULE_FUNCTION = r"""
CREATE OR REPLACE FUNCTION request_cmd.schedule_recovery_reassessment(
    p_organization_id uuid,
    p_service_queue_id uuid,
    p_revision bigint
) RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = request_engine, request_cmd, pg_catalog
AS $function$
DECLARE
    v_dedupe_key text;
    v_inserted boolean := false;
    v_context text := COALESCE(
        current_setting('request_engine.organization_id', true),
        ''
    );
BEGIN
    IF p_service_queue_id IS NULL OR p_revision IS NULL OR p_revision <= 0 THEN
        RETURN false;
    END IF;
    IF v_context <> '' AND v_context <> p_organization_id::text THEN
        RAISE EXCEPTION
            'schedule_recovery_reassessment rejects foreign tenant authority'
            USING ERRCODE = '23514';
    END IF;

    v_dedupe_key := format('f5-reassessment:%s:%s', p_service_queue_id, p_revision);

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
            'source_revision', p_revision
        ),
        v_dedupe_key,
        clock_timestamp(),
        clock_timestamp(),
        8
    )
    ON CONFLICT (organization_id, dedupe_key) DO NOTHING
    RETURNING true INTO v_inserted;

    UPDATE request_engine.scheduled_actions
       SET status = 'cancelled',
           updated_at = clock_timestamp()
     WHERE organization_id = p_organization_id
       AND owner_module = 'operational_recovery'
       AND action_type = 'reassess_recovery_scope'
       AND subject_id = p_service_queue_id
       AND status = 'pending'
       AND dedupe_key <> v_dedupe_key
       AND (payload->>'source_revision')::bigint < p_revision;

    RETURN v_inserted;
END
$function$;
"""

_BUMP_FUNCTION = r"""
CREATE OR REPLACE FUNCTION request_engine.bump_recovery_source_revision(
    p_organization_id uuid,
    p_service_queue_id uuid
) RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = request_engine, request_cmd, pg_catalog
AS $function$
DECLARE
    v_revision bigint;
    v_context text := COALESCE(
        current_setting('request_engine.organization_id', true),
        ''
    );
BEGIN
    IF p_service_queue_id IS NULL THEN
        RETURN;
    END IF;

    IF v_context <> '' AND v_context <> p_organization_id::text THEN
        RAISE EXCEPTION
            'bump_recovery_source_revision rejects foreign tenant authority'
            USING ERRCODE = '23514';
    END IF;

    INSERT INTO request_engine.recovery_source_revisions (
        organization_id, service_queue_id, revision, updated_at
    ) VALUES (
        p_organization_id, p_service_queue_id, 1, clock_timestamp()
    )
    ON CONFLICT (organization_id, service_queue_id)
    DO UPDATE SET
        revision = request_engine.recovery_source_revisions.revision + 1,
        updated_at = clock_timestamp()
    RETURNING revision INTO v_revision;

    PERFORM request_cmd.schedule_recovery_reassessment(
        p_organization_id,
        p_service_queue_id,
        v_revision
    );
END
$function$;
"""


def upgrade() -> None:
    op.execute("SET ROLE request_engine_schema_owner;")
    op.execute("SET search_path = request_engine, request_cmd, pg_catalog;")
    op.execute(_SCHEDULE_FUNCTION)
    op.execute(_BUMP_FUNCTION)
    op.execute(
        "REVOKE ALL ON FUNCTION "
        "request_cmd.schedule_recovery_reassessment(uuid, uuid, bigint) FROM PUBLIC"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION "
        "request_cmd.schedule_recovery_reassessment(uuid, uuid, bigint) "
        "TO request_engine_app"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION "
        "request_engine.bump_recovery_source_revision(uuid, uuid) FROM PUBLIC"
    )
    op.execute("RESET ROLE;")
    op.execute("RESET search_path;")


def downgrade() -> None:
    raise RuntimeError("0019 introduces the F5 coalescing enqueue surface and is not reversible")
