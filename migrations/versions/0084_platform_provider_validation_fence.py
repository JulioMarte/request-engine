"""Fence provider validation to the exact secret version observed during I/O.

Revision ID: 0084_provider_validation_fence
Revises: 0083_provider_secret_resolution

Provider validation runs outside PostgreSQL locks. The commit therefore carries
the binding revision/backend version observed before network I/O and fails if
the governed secret changed while validation was in flight.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0084_provider_validation_fence"
down_revision: str | Sequence[str] | None = "0083_provider_secret_resolution"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEFINER = "request_platform_control_definer"
_RUNTIME = "request_platform_control"
_NEW = (
    "request_platform.validate_platform_configuration_provider"
    "(text,bigint,bigint,integer,text,text)"
)
_OLD = "request_platform.validate_platform_configuration(text,bigint,text,text)"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(
        r"""
        GRANT SELECT (id, backend_version, revision, status)
        ON request_engine.platform_secret_bindings
        TO request_platform_control_definer;

        GRANT USAGE, CREATE ON SCHEMA request_platform
        TO request_platform_control_definer;

        CREATE FUNCTION request_platform.validate_platform_configuration_provider(
            p_configuration_kind text,
            p_revision bigint,
            p_expected_binding_revision bigint,
            p_expected_backend_version integer,
            p_idempotency_key_digest text,
            p_intent_digest text
        )
        RETURNS TABLE (
            configuration_revision_id uuid,
            revision bigint,
            state text
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $function$
        DECLARE
            v_actor_id uuid;
            v_actor_method text;
            v_correlation_id uuid;
            v_replay record;
            v_target record;
            v_binding record;
        BEGIN
            SELECT actor_id, actor_method, correlation_id
              INTO v_actor_id, v_actor_method, v_correlation_id
              FROM request_platform.assert_platform_configuration_actor(
                  'platform.configuration.validate'
              );

            IF p_configuration_kind !~ '^[a-z][a-z0-9_.-]{1,79}$'
               OR p_revision IS NULL OR p_revision < 1
               OR (p_expected_binding_revision IS NOT NULL
                   AND p_expected_binding_revision < 1)
               OR (p_expected_backend_version IS NOT NULL
                   AND p_expected_backend_version < 1)
               OR p_idempotency_key_digest !~ '^[0-9a-f]{64}$'
               OR p_intent_digest !~ '^[0-9a-f]{64}$'
            THEN
                RAISE EXCEPTION 'Platform configuration validation input is invalid'
                    USING ERRCODE = '22023';
            END IF;

            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended(
                    'p7/idempotency/' || v_actor_id::text
                    || '/platform.configuration.validate/'
                    || p_idempotency_key_digest,
                    0
                )
            );

            SELECT
                fact.configuration_revision_id,
                fact.revision,
                fact.intent_digest,
                fact.detail
              INTO v_replay
              FROM request_engine.platform_configuration_facts AS fact
             WHERE fact.actor_principal_id = v_actor_id
               AND fact.capability_key = 'platform.configuration.validate'
               AND fact.idempotency_key_digest = p_idempotency_key_digest;

            IF FOUND THEN
                IF v_replay.intent_digest <> p_intent_digest THEN
                    RAISE EXCEPTION
                        'Idempotency key conflicts with another validation intent'
                        USING ERRCODE = '23505';
                END IF;
                RETURN QUERY
                SELECT
                    v_replay.configuration_revision_id,
                    v_replay.revision,
                    v_replay.detail ->> 'result_state';
                RETURN;
            END IF;

            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended(
                    'p7/configuration-kind/' || p_configuration_kind,
                    0
                )
            );

            SELECT
                revision_row.id,
                revision_row.state,
                revision_row.secret_binding_id
              INTO v_target
              FROM request_engine.platform_configuration_revisions AS revision_row
             WHERE revision_row.configuration_kind = p_configuration_kind
               AND revision_row.revision = p_revision
             FOR UPDATE;

            IF NOT FOUND THEN
                RAISE EXCEPTION 'Platform configuration revision does not exist'
                    USING ERRCODE = 'P0002';
            END IF;
            IF v_target.state <> 'draft' THEN
                RAISE EXCEPTION 'Platform configuration revision is not a draft'
                    USING ERRCODE = '40001';
            END IF;

            IF v_target.secret_binding_id IS NULL THEN
                IF p_expected_binding_revision IS NOT NULL
                   OR p_expected_backend_version IS NOT NULL
                THEN
                    RAISE EXCEPTION 'Unexpected provider secret precondition'
                        USING ERRCODE = '40001';
                END IF;
            ELSE
                IF p_expected_binding_revision IS NULL
                   OR p_expected_backend_version IS NULL
                THEN
                    RAISE EXCEPTION 'Provider secret precondition is required'
                        USING ERRCODE = '40001';
                END IF;

                SELECT binding.revision, binding.backend_version, binding.status
                  INTO v_binding
                  FROM request_engine.platform_secret_bindings AS binding
                 WHERE binding.id = v_target.secret_binding_id
                 FOR SHARE;

                IF NOT FOUND
                   OR v_binding.status <> 'active'
                   OR v_binding.revision <> p_expected_binding_revision
                   OR v_binding.backend_version <> p_expected_backend_version
                THEN
                    RAISE EXCEPTION 'Provider secret changed during validation'
                        USING ERRCODE = '40001';
                END IF;
            END IF;

            UPDATE request_engine.platform_configuration_revisions
               SET state = 'validated',
                   validated_at = clock_timestamp()
             WHERE id = v_target.id;

            INSERT INTO request_engine.platform_configuration_facts (
                event_kind,
                configuration_revision_id,
                configuration_kind,
                revision,
                secret_binding_id,
                actor_principal_id,
                actor_authentication_method,
                correlation_id,
                detail,
                capability_key,
                idempotency_key_digest,
                intent_digest
            ) VALUES (
                'validated',
                v_target.id,
                p_configuration_kind,
                p_revision,
                v_target.secret_binding_id,
                v_actor_id,
                v_actor_method,
                v_correlation_id,
                jsonb_build_object(
                    'result_state', 'validated',
                    'secret_binding_revision', p_expected_binding_revision,
                    'backend_version', p_expected_backend_version
                ),
                'platform.configuration.validate',
                p_idempotency_key_digest,
                p_intent_digest
            );

            RETURN QUERY SELECT v_target.id, p_revision, 'validated'::text;
        END
        $function$;
        """
    )
    op.execute(f"ALTER FUNCTION {_NEW} OWNER TO {_DEFINER}")
    op.execute(f"REVOKE ALL ON FUNCTION {_NEW} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {_NEW} TO {_RUNTIME}")
    op.execute(f"REVOKE EXECUTE ON FUNCTION {_OLD} FROM {_RUNTIME}")
    op.execute(f"REVOKE CREATE ON SCHEMA request_platform FROM {_DEFINER}")


def downgrade() -> None:
    raise RuntimeError("Provider validation fencing is security hardening; roll forward")
