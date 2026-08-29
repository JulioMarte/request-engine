"""Harden F5 bump tenant authority and add intake-control freshness.

Two normative closures on top of the recovery workflow tranche:

1. Contract 32 section 15-H: no SECURITY DEFINER path may accept
   caller-supplied foreign tenant authority. 0013 rewrote
   ``bump_recovery_source_revision`` so it derives tenant context from its
   arguments, so any future EXECUTE grant would become a cross-tenant write
   path. The function now rejects a call whose session tenant context differs
   from the requested organization. Context-less administrative sessions keep
   the pre-0013 semantics: FORCE RLS decides for non-bypass roles and BYPASSRLS
   administrators keep working, so no tenant-scoped session can pivot tenants
   through the fence.
2. Contract 32 section 12: every successful intake mutation schedules a fresh
   reprojection. Queue intake-control writes now bump the recovery source
   revision through the same fenced bump path; bookkeeping-only updates are
   ignored.

Immutability/downgrade note: F5 freshness migrations are not reversible in
place; downgrade raises like every other tranche migration.
"""

from alembic import op

revision = "0016_f5_bump_guard_freshness"
down_revision = "0015_f5_commitment_freshness"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
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
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION request_engine.bump_intake_control_recovery_source_revision()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = request_engine, pg_catalog
        AS $function$
        BEGIN
            IF NEW.accepting IS NOT DISTINCT FROM OLD.accepting
               AND NEW.reason IS NOT DISTINCT FROM OLD.reason
               AND NEW.effective_until IS NOT DISTINCT FROM OLD.effective_until THEN
                RETURN NULL;
            END IF;
            PERFORM request_engine.bump_recovery_source_revision(
                NEW.organization_id,
                NEW.service_queue_id
            );
            RETURN NULL;
        END
        $function$;
        """
    )
    op.execute(
        "REVOKE ALL ON FUNCTION "
        "request_engine.bump_intake_control_recovery_source_revision() FROM PUBLIC"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION "
        "request_engine.bump_recovery_source_revision(uuid, uuid) FROM PUBLIC"
    )
    op.execute(
        """
        CREATE TRIGGER service_queue_intake_controls_bump_recovery_source_revision
        AFTER UPDATE OF accepting, reason, effective_until
        ON request_engine.service_queue_intake_controls
        FOR EACH ROW
        EXECUTE FUNCTION request_engine.bump_intake_control_recovery_source_revision()
        """
    )


def downgrade() -> None:
    raise RuntimeError("0016_f5_bump_guard_intake_freshness is not reversible in place")
