"""Record SMTP/provider test outcomes as append-only P7 facts.

Revision ID: 0086_provider_test_facts
Revises: 0085_provider_candidate_read

Provider tests are observations, not activation. Their result is recorded against
the exact candidate and secret version used for the test. UNKNOWN is durable and
must never be silently converted into a retry/delivered assertion.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0086_provider_test_facts"
down_revision: str | Sequence[str] | None = "0085_provider_candidate_read"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEFINER = "request_platform_control_definer"
_RUNTIME = "request_platform_control"
_SIGNATURE = (
    "request_platform.record_platform_provider_test"
    "(text,bigint,bigint,integer,text,text,text,text)"
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(
        """
        ALTER TABLE request_engine.platform_configuration_facts
            DROP CONSTRAINT platform_configuration_facts_kind_check;
        ALTER TABLE request_engine.platform_configuration_facts
            ADD CONSTRAINT platform_configuration_facts_kind_check CHECK (
                event_kind IN (
                    'staged',
                    'validated',
                    'activated',
                    'superseded',
                    'disabled',
                    'secret_bound',
                    'secret_rotated',
                    'secret_revoked',
                    'provider_tested'
                )
            );
        GRANT USAGE, CREATE ON SCHEMA request_platform
            TO request_platform_control_definer;
        """
    )
    op.execute(
        r"""
        CREATE FUNCTION request_platform.record_platform_provider_test(
            p_configuration_kind text,
            p_revision bigint,
            p_expected_binding_revision bigint,
            p_expected_backend_version integer,
            p_outcome text,
            p_detail_code text,
            p_idempotency_key_digest text,
            p_intent_digest text
        )
        RETURNS uuid
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $function$
        DECLARE
            v_actor_id uuid;
            v_actor_method text;
            v_correlation_id uuid;
            v_target record;
            v_binding record;
            v_existing record;
            v_fact_id uuid;
        BEGIN
            SELECT actor_id, actor_method, correlation_id
              INTO v_actor_id, v_actor_method, v_correlation_id
              FROM request_platform.assert_platform_configuration_actor(
                  'platform.provider.test'
              );

            IF p_configuration_kind !~ '^[a-z][a-z0-9_.-]{1,79}$'
               OR p_revision IS NULL OR p_revision < 1
               OR p_outcome NOT IN ('delivered', 'failed', 'unknown')
               OR p_detail_code !~ '^[a-z][a-z0-9_.-]{1,127}$'
               OR p_idempotency_key_digest !~ '^[0-9a-f]{64}$'
               OR p_intent_digest !~ '^[0-9a-f]{64}$'
            THEN
                RAISE EXCEPTION 'Platform provider test input is invalid'
                    USING ERRCODE = '22023';
            END IF;

            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended(
                    'p7/idempotency/' || v_actor_id::text
                    || '/platform.provider.test/' || p_idempotency_key_digest,
                    0
                )
            );

            SELECT fact.id, fact.intent_digest
              INTO v_existing
              FROM request_engine.platform_configuration_facts AS fact
             WHERE fact.actor_principal_id = v_actor_id
               AND fact.capability_key = 'platform.provider.test'
               AND fact.idempotency_key_digest = p_idempotency_key_digest;

            IF FOUND THEN
                IF v_existing.intent_digest <> p_intent_digest THEN
                    RAISE EXCEPTION 'Idempotency key conflicts with another provider test'
                        USING ERRCODE = '23505';
                END IF;
                RETURN v_existing.id;
            END IF;

            SELECT r.id, r.secret_binding_id, r.state
              INTO v_target
              FROM request_engine.platform_configuration_revisions AS r
             WHERE r.configuration_kind = p_configuration_kind
               AND r.revision = p_revision
             FOR SHARE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Platform configuration revision does not exist'
                    USING ERRCODE = 'P0002';
            END IF;
            IF v_target.state NOT IN ('validated', 'active') THEN
                RAISE EXCEPTION 'Platform provider test requires validated configuration'
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
                    RAISE EXCEPTION 'Provider secret changed during test'
                        USING ERRCODE = '40001';
                END IF;
            END IF;

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
                'provider_tested',
                v_target.id,
                p_configuration_kind,
                p_revision,
                v_target.secret_binding_id,
                v_actor_id,
                v_actor_method,
                v_correlation_id,
                jsonb_build_object(
                    'outcome', p_outcome,
                    'detail_code', p_detail_code,
                    'secret_binding_revision', p_expected_binding_revision,
                    'backend_version', p_expected_backend_version
                ),
                'platform.provider.test',
                p_idempotency_key_digest,
                p_intent_digest
            )
            RETURNING id INTO v_fact_id;

            RETURN v_fact_id;
        END
        $function$;
        """
    )
    op.execute(f"ALTER FUNCTION {_SIGNATURE} OWNER TO {_DEFINER}")
    op.execute(f"REVOKE ALL ON FUNCTION {_SIGNATURE} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {_SIGNATURE} TO {_RUNTIME}")
    op.execute(f"REVOKE CREATE ON SCHEMA request_platform FROM {_DEFINER}")


def downgrade() -> None:
    raise RuntimeError("Provider test facts are append-only accepted history; roll forward")
