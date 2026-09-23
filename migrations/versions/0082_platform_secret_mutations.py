"""Add durable cross-system platform secret mutation orchestration.

Revision ID: 0082_platform_secret_mutations
Revises: 0081_platform_config_read

PostgreSQL and OpenBao cannot share one transaction. P7-D therefore prepares a
plaintext-free operation before backend I/O, records the backend-applied version
in a second transaction, and only then commits the existing governed binding
command. A stale metadata commit becomes durable ``reconcile_required`` state
instead of being hidden as an apparently atomic failure.

The P7-B direct secret metadata functions remain historical executable objects
owned by the control definer, but the runtime login loses EXECUTE on them so
product code cannot bypass this ledger.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0082_platform_secret_mutations"
down_revision: str | Sequence[str] | None = "0081_platform_config_read"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONTROL_DEFINER = "request_platform_control_definer"
_RUNTIME = "request_platform_control"

_NEW_FUNCTIONS = (
    "request_platform.prepare_platform_secret_mutation(text,text,text,uuid,bigint,integer,text,text)",
    "request_platform.mark_platform_secret_backend_applied(uuid,integer)",
    "request_platform.commit_platform_secret_mutation(uuid)",
)

_OLD_DIRECT_FUNCTIONS = (
    "request_platform.record_platform_secret_binding(text,text,uuid,integer,text,text)",
    "request_platform.commit_platform_secret_rotation(uuid,bigint,integer,integer,text,text)",
    "request_platform.revoke_platform_secret_binding(uuid,bigint,integer,text,text)",
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(
        r"""
        CREATE TABLE request_engine.platform_secret_mutations (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            operation_kind text NOT NULL
                CHECK (operation_kind IN ('create', 'rotate', 'revoke')),
            capability_key text NOT NULL
                CHECK (capability_key IN (
                    'platform.secret.write',
                    'platform.secret.rotate',
                    'platform.secret.revoke'
                )),
            actor_principal_id uuid NOT NULL,
            actor_authentication_method text NOT NULL,
            correlation_id uuid NOT NULL,
            binding_id uuid,
            secret_id uuid NOT NULL,
            purpose text NOT NULL
                CHECK (purpose ~ '^[a-z][a-z0-9_.-]{1,127}$'),
            backend text NOT NULL CHECK (backend IN ('openbao', 'vault')),
            expected_binding_revision bigint CHECK (
                expected_binding_revision IS NULL OR expected_binding_revision > 0
            ),
            expected_backend_version integer CHECK (
                expected_backend_version IS NULL OR expected_backend_version > 0
            ),
            applied_backend_version integer CHECK (
                applied_backend_version IS NULL OR applied_backend_version > 0
            ),
            state text NOT NULL DEFAULT 'prepared'
                CHECK (state IN (
                    'prepared',
                    'backend_applied',
                    'committed',
                    'reconcile_required'
                )),
            idempotency_key_digest text NOT NULL
                CHECK (idempotency_key_digest ~ '^[0-9a-f]{64}$'),
            intent_digest text NOT NULL
                CHECK (intent_digest ~ '^[0-9a-f]{64}$'),
            result_binding_id uuid,
            result_binding_revision bigint,
            result_binding_status text,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            backend_applied_at timestamptz,
            committed_at timestamptz,
            reconcile_required_at timestamptz,
            CHECK (
                (operation_kind = 'create'
                    AND binding_id IS NULL
                    AND expected_binding_revision IS NULL
                    AND expected_backend_version IS NULL)
                OR
                (operation_kind IN ('rotate', 'revoke')
                    AND binding_id IS NOT NULL
                    AND expected_binding_revision IS NOT NULL
                    AND expected_backend_version IS NOT NULL)
            ),
            CHECK (
                (state = 'prepared'
                    AND applied_backend_version IS NULL
                    AND backend_applied_at IS NULL
                    AND committed_at IS NULL
                    AND reconcile_required_at IS NULL)
                OR
                (state = 'backend_applied'
                    AND applied_backend_version IS NOT NULL
                    AND backend_applied_at IS NOT NULL
                    AND committed_at IS NULL
                    AND reconcile_required_at IS NULL)
                OR
                (state = 'committed'
                    AND applied_backend_version IS NOT NULL
                    AND backend_applied_at IS NOT NULL
                    AND committed_at IS NOT NULL
                    AND reconcile_required_at IS NULL
                    AND result_binding_id IS NOT NULL
                    AND result_binding_revision IS NOT NULL
                    AND result_binding_status IS NOT NULL)
                OR
                (state = 'reconcile_required'
                    AND applied_backend_version IS NOT NULL
                    AND backend_applied_at IS NOT NULL
                    AND committed_at IS NULL
                    AND reconcile_required_at IS NOT NULL)
            ),
            UNIQUE (actor_principal_id, capability_key, idempotency_key_digest)
        );

        CREATE UNIQUE INDEX platform_secret_mutations_open_binding_uq
            ON request_engine.platform_secret_mutations (binding_id)
            WHERE binding_id IS NOT NULL
              AND state IN ('prepared', 'backend_applied', 'reconcile_required');

        CREATE UNIQUE INDEX platform_secret_mutations_open_create_purpose_uq
            ON request_engine.platform_secret_mutations (purpose)
            WHERE operation_kind = 'create'
              AND state IN ('prepared', 'backend_applied', 'reconcile_required');

        CREATE INDEX platform_secret_mutations_state_created_idx
            ON request_engine.platform_secret_mutations (state, created_at);

        ALTER TABLE request_engine.platform_secret_mutations
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON request_engine.platform_secret_mutations FROM PUBLIC;
        GRANT SELECT (
            id,
            operation_kind,
            capability_key,
            actor_principal_id,
            actor_authentication_method,
            correlation_id,
            binding_id,
            secret_id,
            purpose,
            backend,
            expected_binding_revision,
            expected_backend_version,
            applied_backend_version,
            state,
            idempotency_key_digest,
            intent_digest,
            result_binding_id,
            result_binding_revision,
            result_binding_status,
            created_at,
            backend_applied_at,
            committed_at,
            reconcile_required_at
        ),
        INSERT (
            operation_kind,
            capability_key,
            actor_principal_id,
            actor_authentication_method,
            correlation_id,
            binding_id,
            secret_id,
            purpose,
            backend,
            expected_binding_revision,
            expected_backend_version,
            idempotency_key_digest,
            intent_digest
        ),
        UPDATE (
            state,
            applied_backend_version,
            backend_applied_at,
            reconcile_required_at,
            result_binding_id,
            result_binding_revision,
            result_binding_status,
            committed_at
        )
        ON request_engine.platform_secret_mutations
        TO request_platform_control_definer;

        GRANT USAGE, CREATE ON SCHEMA request_platform
            TO request_platform_control_definer;
        """
    )

    op.execute(
        r"""
        CREATE FUNCTION request_platform.prepare_platform_secret_mutation(
            p_operation_kind text,
            p_purpose text,
            p_backend text,
            p_binding_id uuid,
            p_expected_binding_revision bigint,
            p_expected_backend_version integer,
            p_idempotency_key_digest text,
            p_intent_digest text
        )
        RETURNS TABLE (
            operation_id uuid,
            operation_kind text,
            binding_id uuid,
            secret_id uuid,
            purpose text,
            backend text,
            expected_binding_revision bigint,
            expected_backend_version integer,
            applied_backend_version integer,
            operation_state text,
            result_binding_id uuid,
            result_binding_revision bigint,
            result_binding_status text
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $function$
        DECLARE
            v_capability text;
            v_actor_id uuid;
            v_actor_method text;
            v_correlation_id uuid;
            v_existing request_engine.platform_secret_mutations%ROWTYPE;
            v_binding request_engine.platform_secret_bindings%ROWTYPE;
            v_operation request_engine.platform_secret_mutations%ROWTYPE;
        BEGIN
            v_capability := CASE p_operation_kind
                WHEN 'create' THEN 'platform.secret.write'
                WHEN 'rotate' THEN 'platform.secret.rotate'
                WHEN 'revoke' THEN 'platform.secret.revoke'
                ELSE NULL
            END;
            IF v_capability IS NULL
               OR p_idempotency_key_digest !~ '^[0-9a-f]{64}$'
               OR p_intent_digest !~ '^[0-9a-f]{64}$'
            THEN
                RAISE EXCEPTION 'Platform secret mutation input is invalid'
                    USING ERRCODE = '22023';
            END IF;

            SELECT actor_id, actor_method, correlation_id
              INTO v_actor_id, v_actor_method, v_correlation_id
              FROM request_platform.assert_platform_configuration_actor(v_capability);

            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended(
                    'p7/secret/idempotency/' || v_actor_id::text || '/'
                    || v_capability || '/' || p_idempotency_key_digest,
                    0
                )
            );

            SELECT *
              INTO v_existing
              FROM request_engine.platform_secret_mutations AS mutation
             WHERE mutation.actor_principal_id = v_actor_id
               AND mutation.capability_key = v_capability
               AND mutation.idempotency_key_digest = p_idempotency_key_digest;

            IF FOUND THEN
                IF v_existing.intent_digest <> p_intent_digest THEN
                    RAISE EXCEPTION 'Idempotency key conflicts with another secret intent'
                        USING ERRCODE = '23505';
                END IF;
                RETURN QUERY SELECT
                    v_existing.id, v_existing.operation_kind, v_existing.binding_id,
                    v_existing.secret_id, v_existing.purpose, v_existing.backend,
                    v_existing.expected_binding_revision,
                    v_existing.expected_backend_version,
                    v_existing.applied_backend_version, v_existing.state,
                    v_existing.result_binding_id, v_existing.result_binding_revision,
                    v_existing.result_binding_status;
                RETURN;
            END IF;

            IF p_operation_kind = 'create' THEN
                IF p_binding_id IS NOT NULL
                   OR p_expected_binding_revision IS NOT NULL
                   OR p_expected_backend_version IS NOT NULL
                   OR p_purpose !~ '^[a-z][a-z0-9_.-]{1,127}$'
                   OR p_backend NOT IN ('openbao', 'vault')
                THEN
                    RAISE EXCEPTION 'Platform secret create input is invalid'
                        USING ERRCODE = '22023';
                END IF;

                PERFORM pg_catalog.pg_advisory_xact_lock(
                    pg_catalog.hashtextextended('p7/secret/purpose/' || p_purpose, 0)
                );
                IF EXISTS (
                    SELECT 1
                      FROM request_engine.platform_secret_bindings AS binding
                     WHERE binding.purpose = p_purpose
                       AND binding.status = 'active'
                ) THEN
                    RAISE EXCEPTION 'Active platform secret purpose already exists'
                        USING ERRCODE = '23505';
                END IF;

                INSERT INTO request_engine.platform_secret_mutations (
                    operation_kind, capability_key, actor_principal_id,
                    actor_authentication_method, correlation_id, binding_id,
                    secret_id, purpose, backend, expected_binding_revision,
                    expected_backend_version, idempotency_key_digest, intent_digest
                ) VALUES (
                    p_operation_kind, v_capability, v_actor_id, v_actor_method,
                    v_correlation_id, NULL, gen_random_uuid(), p_purpose, p_backend,
                    NULL, NULL, p_idempotency_key_digest, p_intent_digest
                )
                RETURNING * INTO v_operation;
            ELSE
                IF p_binding_id IS NULL
                   OR p_purpose IS NOT NULL
                   OR p_backend IS NOT NULL
                   OR p_expected_binding_revision IS NULL
                   OR p_expected_binding_revision < 1
                   OR p_expected_backend_version IS NULL
                   OR p_expected_backend_version < 1
                THEN
                    RAISE EXCEPTION 'Platform secret mutation precondition is invalid'
                        USING ERRCODE = '22023';
                END IF;

                SELECT *
                  INTO v_binding
                  FROM request_engine.platform_secret_bindings AS binding
                 WHERE binding.id = p_binding_id
                 FOR UPDATE;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'Platform secret binding does not exist'
                        USING ERRCODE = 'P0002';
                END IF;
                IF v_binding.status <> 'active'
                   OR v_binding.revision <> p_expected_binding_revision
                   OR v_binding.backend_version <> p_expected_backend_version
                THEN
                    RAISE EXCEPTION 'Platform secret binding revision is stale'
                        USING ERRCODE = '40001';
                END IF;
                IF EXISTS (
                    SELECT 1
                      FROM request_engine.platform_secret_mutations AS mutation
                     WHERE mutation.binding_id = p_binding_id
                       AND mutation.state IN (
                           'prepared', 'backend_applied', 'reconcile_required'
                       )
                ) THEN
                    RAISE EXCEPTION 'Platform secret binding has an unfinished mutation'
                        USING ERRCODE = '40001';
                END IF;

                INSERT INTO request_engine.platform_secret_mutations (
                    operation_kind, capability_key, actor_principal_id,
                    actor_authentication_method, correlation_id, binding_id,
                    secret_id, purpose, backend, expected_binding_revision,
                    expected_backend_version, idempotency_key_digest, intent_digest
                ) VALUES (
                    p_operation_kind, v_capability, v_actor_id, v_actor_method,
                    v_correlation_id, p_binding_id, v_binding.secret_id,
                    v_binding.purpose, v_binding.backend,
                    p_expected_binding_revision, p_expected_backend_version,
                    p_idempotency_key_digest, p_intent_digest
                )
                RETURNING * INTO v_operation;
            END IF;

            RETURN QUERY SELECT
                v_operation.id, v_operation.operation_kind, v_operation.binding_id,
                v_operation.secret_id, v_operation.purpose, v_operation.backend,
                v_operation.expected_binding_revision,
                v_operation.expected_backend_version,
                v_operation.applied_backend_version, v_operation.state,
                v_operation.result_binding_id, v_operation.result_binding_revision,
                v_operation.result_binding_status;
        END
        $function$;

        CREATE FUNCTION request_platform.mark_platform_secret_backend_applied(
            p_operation_id uuid,
            p_applied_backend_version integer
        )
        RETURNS TABLE (
            operation_id uuid,
            operation_kind text,
            binding_id uuid,
            secret_id uuid,
            purpose text,
            backend text,
            expected_binding_revision bigint,
            expected_backend_version integer,
            applied_backend_version integer,
            operation_state text,
            result_binding_id uuid,
            result_binding_revision bigint,
            result_binding_status text
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $function$
        DECLARE
            v_operation request_engine.platform_secret_mutations%ROWTYPE;
            v_actor_id uuid;
            v_ignore_method text;
            v_ignore_correlation uuid;
        BEGIN
            SELECT *
              INTO v_operation
              FROM request_engine.platform_secret_mutations
             WHERE id = p_operation_id
             FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Platform secret mutation does not exist'
                    USING ERRCODE = 'P0002';
            END IF;

            SELECT actor_id, actor_method, correlation_id
              INTO v_actor_id, v_ignore_method, v_ignore_correlation
              FROM request_platform.assert_platform_configuration_actor(
                  v_operation.capability_key
              );
            IF v_actor_id <> v_operation.actor_principal_id THEN
                RAISE EXCEPTION 'Platform secret mutation belongs to another actor'
                    USING ERRCODE = '42501';
            END IF;

            IF v_operation.state IN ('committed', 'reconcile_required') THEN
                RETURN QUERY SELECT
                    v_operation.id, v_operation.operation_kind, v_operation.binding_id,
                    v_operation.secret_id, v_operation.purpose, v_operation.backend,
                    v_operation.expected_binding_revision,
                    v_operation.expected_backend_version,
                    v_operation.applied_backend_version, v_operation.state,
                    v_operation.result_binding_id, v_operation.result_binding_revision,
                    v_operation.result_binding_status;
                RETURN;
            END IF;

            IF p_applied_backend_version IS NULL OR p_applied_backend_version < 1
               OR (v_operation.operation_kind = 'rotate'
                   AND p_applied_backend_version <= v_operation.expected_backend_version)
               OR (v_operation.operation_kind = 'revoke'
                   AND p_applied_backend_version <> v_operation.expected_backend_version)
            THEN
                RAISE EXCEPTION 'Applied backend version is invalid'
                    USING ERRCODE = '22023';
            END IF;

            IF v_operation.state = 'backend_applied' THEN
                IF v_operation.applied_backend_version <> p_applied_backend_version THEN
                    RAISE EXCEPTION 'Backend-applied version changed'
                        USING ERRCODE = '40001';
                END IF;
            ELSE
                UPDATE request_engine.platform_secret_mutations
                   SET state = 'backend_applied',
                       applied_backend_version = p_applied_backend_version,
                       backend_applied_at = clock_timestamp()
                 WHERE id = p_operation_id
                RETURNING * INTO v_operation;
            END IF;

            RETURN QUERY SELECT
                v_operation.id, v_operation.operation_kind, v_operation.binding_id,
                v_operation.secret_id, v_operation.purpose, v_operation.backend,
                v_operation.expected_binding_revision,
                v_operation.expected_backend_version,
                v_operation.applied_backend_version, v_operation.state,
                v_operation.result_binding_id, v_operation.result_binding_revision,
                v_operation.result_binding_status;
        END
        $function$;

        CREATE FUNCTION request_platform.commit_platform_secret_mutation(
            p_operation_id uuid
        )
        RETURNS TABLE (
            operation_id uuid,
            operation_kind text,
            binding_id uuid,
            secret_id uuid,
            purpose text,
            backend text,
            expected_binding_revision bigint,
            expected_backend_version integer,
            applied_backend_version integer,
            operation_state text,
            result_binding_id uuid,
            result_binding_revision bigint,
            result_binding_status text
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $function$
        DECLARE
            v_operation request_engine.platform_secret_mutations%ROWTYPE;
            v_actor_id uuid;
            v_ignore_method text;
            v_ignore_correlation uuid;
            v_result record;
        BEGIN
            SELECT *
              INTO v_operation
              FROM request_engine.platform_secret_mutations
             WHERE id = p_operation_id
             FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Platform secret mutation does not exist'
                    USING ERRCODE = 'P0002';
            END IF;

            SELECT actor_id, actor_method, correlation_id
              INTO v_actor_id, v_ignore_method, v_ignore_correlation
              FROM request_platform.assert_platform_configuration_actor(
                  v_operation.capability_key
              );
            IF v_actor_id <> v_operation.actor_principal_id THEN
                RAISE EXCEPTION 'Platform secret mutation belongs to another actor'
                    USING ERRCODE = '42501';
            END IF;

            IF v_operation.state IN ('committed', 'reconcile_required') THEN
                RETURN QUERY SELECT
                    v_operation.id, v_operation.operation_kind, v_operation.binding_id,
                    v_operation.secret_id, v_operation.purpose, v_operation.backend,
                    v_operation.expected_binding_revision,
                    v_operation.expected_backend_version,
                    v_operation.applied_backend_version, v_operation.state,
                    v_operation.result_binding_id, v_operation.result_binding_revision,
                    v_operation.result_binding_status;
                RETURN;
            END IF;
            IF v_operation.state <> 'backend_applied' THEN
                RAISE EXCEPTION 'Backend mutation has not been recorded'
                    USING ERRCODE = '55000';
            END IF;

            BEGIN
                IF v_operation.operation_kind = 'create' THEN
                    SELECT * INTO v_result
                      FROM request_platform.record_platform_secret_binding(
                          v_operation.purpose,
                          v_operation.backend,
                          v_operation.secret_id,
                          v_operation.applied_backend_version,
                          v_operation.idempotency_key_digest,
                          v_operation.intent_digest
                      );
                ELSIF v_operation.operation_kind = 'rotate' THEN
                    SELECT * INTO v_result
                      FROM request_platform.commit_platform_secret_rotation(
                          v_operation.binding_id,
                          v_operation.expected_binding_revision,
                          v_operation.expected_backend_version,
                          v_operation.applied_backend_version,
                          v_operation.idempotency_key_digest,
                          v_operation.intent_digest
                      );
                ELSE
                    SELECT * INTO v_result
                      FROM request_platform.revoke_platform_secret_binding(
                          v_operation.binding_id,
                          v_operation.expected_binding_revision,
                          v_operation.expected_backend_version,
                          v_operation.idempotency_key_digest,
                          v_operation.intent_digest
                      );
                END IF;
            EXCEPTION
                WHEN SQLSTATE '40001' OR unique_violation THEN
                    UPDATE request_engine.platform_secret_mutations
                       SET state = 'reconcile_required',
                           reconcile_required_at = clock_timestamp()
                     WHERE id = p_operation_id
                    RETURNING * INTO v_operation;

                    RETURN QUERY SELECT
                        v_operation.id, v_operation.operation_kind,
                        v_operation.binding_id, v_operation.secret_id,
                        v_operation.purpose, v_operation.backend,
                        v_operation.expected_binding_revision,
                        v_operation.expected_backend_version,
                        v_operation.applied_backend_version, v_operation.state,
                        v_operation.result_binding_id,
                        v_operation.result_binding_revision,
                        v_operation.result_binding_status;
                    RETURN;
            END;

            UPDATE request_engine.platform_secret_mutations
               SET state = 'committed',
                   result_binding_id = v_result.binding_id,
                   result_binding_revision = v_result.revision,
                   result_binding_status = v_result.status,
                   committed_at = clock_timestamp()
             WHERE id = p_operation_id
            RETURNING * INTO v_operation;

            RETURN QUERY SELECT
                v_operation.id, v_operation.operation_kind, v_operation.binding_id,
                v_operation.secret_id, v_operation.purpose, v_operation.backend,
                v_operation.expected_binding_revision,
                v_operation.expected_backend_version,
                v_operation.applied_backend_version, v_operation.state,
                v_operation.result_binding_id, v_operation.result_binding_revision,
                v_operation.result_binding_status;
        END
        $function$;
        """
    )

    for signature in _NEW_FUNCTIONS:
        op.execute(f"ALTER FUNCTION {signature} OWNER TO {_CONTROL_DEFINER}")
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO {_RUNTIME}")

    for signature in _OLD_DIRECT_FUNCTIONS:
        op.execute(f"REVOKE EXECUTE ON FUNCTION {signature} FROM {_RUNTIME}")

    op.execute(f"REVOKE CREATE ON SCHEMA request_platform FROM {_CONTROL_DEFINER}")


def downgrade() -> None:
    raise RuntimeError(
        "Durable platform secret mutation orchestration is security history; roll forward"
    )
