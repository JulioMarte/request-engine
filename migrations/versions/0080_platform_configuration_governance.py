"""Govern platform configuration revisions and secret-binding metadata.

Revision ID: 0080_platform_config_governance
Revises: 0079_recovery_delivery_reclaim

P7-B turns the private 0069 foundation into a reviewed platform-control
boundary. PostgreSQL remains authoritative for configuration lifecycle and
secret-binding metadata; plaintext secret material remains outside PostgreSQL.

The migration also appends platform-owner-v3 and automatically adopts only the
new v3 capabilities when a Platform Owner lifecycle grant is created. Existing
owners are upgraded append-only without mutating older policy rows.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0080_platform_config_governance"
down_revision: str | Sequence[str] | None = "0079_recovery_delivery_reclaim"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONTROL_DEFINER = "request_platform_control_definer"
_RUNTIME = "request_platform_control"

_INTERNAL_FUNCTIONS = (
    "request_platform.assert_platform_configuration_actor(text)",
)

_RUNTIME_FUNCTIONS = (
    "request_platform.read_platform_configuration_revisions(text)",
    "request_platform.read_platform_secret_binding(uuid)",
    (
        "request_platform.stage_platform_configuration("
        "text,text,jsonb,uuid,text,text)"
    ),
    (
        "request_platform.validate_platform_configuration("
        "text,bigint,text,text)"
    ),
    (
        "request_platform.activate_platform_configuration("
        "text,bigint,bigint,text,text)"
    ),
    (
        "request_platform.disable_platform_configuration("
        "text,bigint,text,text)"
    ),
    (
        "request_platform.record_platform_secret_binding("
        "text,text,uuid,integer,text,text)"
    ),
    (
        "request_platform.commit_platform_secret_rotation("
        "uuid,bigint,integer,integer,text,text)"
    ),
    (
        "request_platform.revoke_platform_secret_binding("
        "uuid,bigint,integer,text,text)"
    ),
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")

    # Append, never mutate, the Platform Owner policy catalog. New capabilities
    # are deliberately non-delegable and are adopted from the v3-v2 delta.
    op.execute(
        r"""
        INSERT INTO request_engine.platform_owner_policies (
            policy_key,
            revision,
            grants
        )
        SELECT
            'platform-owner-v3',
            3,
            grants || '[
                {"capability_key":"platform.configuration.read","delegable":false},
                {"capability_key":"platform.configuration.stage","delegable":false},
                {"capability_key":"platform.configuration.validate","delegable":false},
                {"capability_key":"platform.configuration.activate","delegable":false},
                {"capability_key":"platform.configuration.disable","delegable":false},
                {"capability_key":"platform.secret.write","delegable":false},
                {"capability_key":"platform.secret.rotate","delegable":false},
                {"capability_key":"platform.secret.revoke","delegable":false},
                {"capability_key":"platform.provider.test","delegable":false},
                {"capability_key":"platform.readiness.read","delegable":false}
            ]'::jsonb
          FROM request_engine.platform_owner_policies
         WHERE policy_key = 'platform-owner-v2';

        GRANT CREATE ON SCHEMA request_engine
            TO request_platform_control_definer;

        CREATE FUNCTION request_engine.adopt_platform_owner_v3()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $function$
        BEGIN
            IF NEW.principal_plane <> 'platform'
               OR NEW.authority_plane <> 'platform'
               OR NEW.status <> 'active'
               OR NEW.capability_key <> 'platform.owner.manage_lifecycle'
            THEN
                RETURN NEW;
            END IF;

            INSERT INTO request_engine.principal_authority_grants (
                principal_id,
                principal_plane,
                authority_plane,
                capability_key,
                delegable,
                granted_by_principal_id,
                provenance_kind,
                provenance_reference
            )
            SELECT
                NEW.principal_id,
                'platform',
                'platform',
                v3_grant.capability_key,
                v3_grant.delegable,
                CASE
                    WHEN NEW.provenance_kind = 'trust_bootstrap'
                    THEN NULL
                    ELSE NEW.granted_by_principal_id
                END,
                CASE
                    WHEN NEW.provenance_kind = 'trust_bootstrap'
                    THEN 'trust_bootstrap'
                    ELSE 'platform_owner_policy_upgrade'
                END,
                'platform-owner-v3-adoption:' || NEW.id::text
              FROM (
                  SELECT
                      item ->> 'capability_key' AS capability_key,
                      coalesce((item ->> 'delegable')::boolean, false) AS delegable
                    FROM request_engine.platform_owner_policies AS policy,
                         LATERAL jsonb_array_elements(policy.grants) AS item
                   WHERE policy.policy_key = 'platform-owner-v3'
              ) AS v3_grant
             WHERE NOT EXISTS (
                       SELECT 1
                         FROM request_engine.platform_owner_policies AS policy,
                              LATERAL jsonb_array_elements(policy.grants) AS item
                        WHERE policy.policy_key = 'platform-owner-v2'
                          AND item ->> 'capability_key' = v3_grant.capability_key
                   )
               AND NOT EXISTS (
                       SELECT 1
                         FROM request_engine.principal_authority_grants AS historical
                        WHERE historical.principal_id = NEW.principal_id
                          AND historical.capability_key = v3_grant.capability_key
                   );

            RETURN NEW;
        END
        $function$;

        ALTER FUNCTION request_engine.adopt_platform_owner_v3()
            OWNER TO request_platform_control_definer;
        REVOKE ALL ON FUNCTION request_engine.adopt_platform_owner_v3()
            FROM PUBLIC;
        REVOKE CREATE ON SCHEMA request_engine
            FROM request_platform_control_definer;

        CREATE TRIGGER principal_authority_adopt_platform_owner_v3
            AFTER INSERT ON request_engine.principal_authority_grants
            FOR EACH ROW
            EXECUTE FUNCTION request_engine.adopt_platform_owner_v3();

        INSERT INTO request_engine.principal_authority_grants (
            principal_id,
            principal_plane,
            authority_plane,
            capability_key,
            delegable,
            granted_by_principal_id,
            provenance_kind,
            provenance_reference
        )
        SELECT
            owner_grant.principal_id,
            'platform',
            'platform',
            v3_grant.capability_key,
            v3_grant.delegable,
            CASE
                WHEN owner_grant.provenance_kind = 'trust_bootstrap'
                THEN NULL
                ELSE owner_grant.granted_by_principal_id
            END,
            CASE
                WHEN owner_grant.provenance_kind = 'trust_bootstrap'
                THEN 'trust_bootstrap'
                ELSE 'platform_owner_policy_upgrade'
            END,
            'platform-owner-v3-upgrade:' || owner_grant.principal_id::text
          FROM request_engine.principal_authority_grants AS owner_grant
          CROSS JOIN (
              SELECT
                  item ->> 'capability_key' AS capability_key,
                  coalesce((item ->> 'delegable')::boolean, false) AS delegable
                FROM request_engine.platform_owner_policies AS policy,
                     LATERAL jsonb_array_elements(policy.grants) AS item
               WHERE policy.policy_key = 'platform-owner-v3'
          ) AS v3_grant
         WHERE owner_grant.principal_plane = 'platform'
           AND owner_grant.authority_plane = 'platform'
           AND owner_grant.status = 'active'
           AND owner_grant.capability_key = 'platform.owner.manage_lifecycle'
           AND NOT EXISTS (
                   SELECT 1
                     FROM request_engine.platform_owner_policies AS policy,
                          LATERAL jsonb_array_elements(policy.grants) AS item
                    WHERE policy.policy_key = 'platform-owner-v2'
                      AND item ->> 'capability_key' = v3_grant.capability_key
               )
           AND NOT EXISTS (
                   SELECT 1
                     FROM request_engine.principal_authority_grants AS historical
                    WHERE historical.principal_id = owner_grant.principal_id
                      AND historical.capability_key = v3_grant.capability_key
               );
        """
    )

    # Extend the append-only fact ledger for platform-scoped command replay.
    # Secret-only facts intentionally have no configuration_kind.
    op.execute(
        r"""
        ALTER TABLE request_engine.platform_configuration_facts
            ALTER COLUMN configuration_kind DROP NOT NULL,
            ADD COLUMN capability_key text,
            ADD COLUMN idempotency_key_digest text,
            ADD COLUMN intent_digest text;

        ALTER TABLE request_engine.platform_configuration_facts
            ADD CONSTRAINT platform_configuration_facts_capability_check
                CHECK (
                    capability_key IS NULL
                    OR capability_key ~ '^[a-z][a-z0-9_.-]{1,127}$'
                ),
            ADD CONSTRAINT platform_configuration_facts_idempotency_check
                CHECK (
                    (
                        idempotency_key_digest IS NULL
                        AND intent_digest IS NULL
                    )
                    OR (
                        idempotency_key_digest ~ '^[0-9a-f]{64}$'
                        AND intent_digest ~ '^[0-9a-f]{64}$'
                    )
                );

        CREATE UNIQUE INDEX platform_configuration_fact_idempotency_uq
            ON request_engine.platform_configuration_facts (
                actor_principal_id,
                capability_key,
                idempotency_key_digest
            )
            WHERE idempotency_key_digest IS NOT NULL;
        """
    )

    # The control definer gets only the columns needed by reviewed functions.
    op.execute(
        f"""
        GRANT SELECT (
            id,
            principal_kind,
            active,
            authority_revision,
            principal_plane
        )
        ON request_engine.principals
        TO {_CONTROL_DEFINER};

        GRANT SELECT (
            principal_id,
            principal_plane,
            authority_plane,
            capability_key,
            status
        )
        ON request_engine.principal_authority_grants
        TO {_CONTROL_DEFINER};

        GRANT SELECT
        ON request_engine.platform_owner_policies
        TO {_CONTROL_DEFINER};

        GRANT SELECT (
            id,
            configuration_kind,
            provider_kind,
            revision,
            configuration,
            secret_binding_id,
            state,
            created_by_principal_id,
            created_at,
            validated_at,
            activated_at,
            disabled_at
        ),
        INSERT (
            id,
            configuration_kind,
            provider_kind,
            revision,
            configuration,
            secret_binding_id,
            created_by_principal_id
        ),
        UPDATE (
            state,
            validated_at,
            activated_at,
            disabled_at
        )
        ON request_engine.platform_configuration_revisions
        TO {_CONTROL_DEFINER};

        GRANT SELECT (
            id,
            purpose,
            backend,
            secret_id,
            backend_version,
            status,
            revision,
            created_at,
            rotated_at,
            revoked_at
        ),
        INSERT (
            id,
            purpose,
            backend,
            secret_id,
            backend_version
        ),
        UPDATE (
            backend_version,
            status,
            revision,
            rotated_at,
            revoked_at
        )
        ON request_engine.platform_secret_bindings
        TO {_CONTROL_DEFINER};

        GRANT SELECT (
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
            intent_digest,
            created_at
        ),
        INSERT (
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
        )
        ON request_engine.platform_configuration_facts
        TO {_CONTROL_DEFINER};

        GRANT USAGE, CREATE ON SCHEMA request_platform
        TO {_CONTROL_DEFINER};
        """
    )

    op.execute(
        r"""
        CREATE FUNCTION request_platform.assert_platform_configuration_actor(
            p_capability text
        )
        RETURNS TABLE (
            actor_id uuid,
            actor_method text,
            correlation_id uuid
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $function$
        DECLARE
            v_actor_id uuid;
            v_actor_revision bigint;
            v_actor_method text;
            v_correlation_id uuid;
            v_actor_kind text;
            v_actor_active boolean;
            v_actor_current_revision bigint;
        BEGIN
            IF p_capability NOT IN (
                'platform.configuration.read',
                'platform.configuration.stage',
                'platform.configuration.validate',
                'platform.configuration.activate',
                'platform.configuration.disable',
                'platform.secret.write',
                'platform.secret.rotate',
                'platform.secret.revoke',
                'platform.provider.test',
                'platform.readiness.read'
            ) THEN
                RAISE EXCEPTION 'Unknown platform configuration capability'
                    USING ERRCODE = '22023';
            END IF;

            BEGIN
                v_actor_id := NULLIF(
                    current_setting(
                        'request_engine.authenticated_principal_id',
                        true
                    ),
                    ''
                )::uuid;
                v_actor_revision := NULLIF(
                    current_setting(
                        'request_engine.authority_revision',
                        true
                    ),
                    ''
                )::bigint;
                v_actor_method := NULLIF(
                    current_setting(
                        'request_engine.authentication_method',
                        true
                    ),
                    ''
                );
                v_correlation_id := NULLIF(
                    current_setting(
                        'request_engine.correlation_id',
                        true
                    ),
                    ''
                )::uuid;
            EXCEPTION WHEN invalid_text_representation THEN
                RAISE EXCEPTION 'Platform actor provenance is malformed'
                    USING ERRCODE = '28000';
            END;

            IF v_actor_id IS NULL
               OR v_actor_revision IS NULL
               OR v_actor_method IS NULL
            THEN
                RAISE EXCEPTION 'Platform actor provenance is required'
                    USING ERRCODE = '28000';
            END IF;

            SELECT
                principal.principal_kind,
                principal.active,
                principal.authority_revision
              INTO
                v_actor_kind,
                v_actor_active,
                v_actor_current_revision
              FROM request_engine.principals AS principal
             WHERE principal.id = v_actor_id
               AND principal.principal_plane = 'platform';

            IF NOT FOUND
               OR NOT v_actor_active
               OR v_actor_kind <> 'human'
            THEN
                RAISE EXCEPTION
                    'Platform configuration requires an active HUMAN principal'
                    USING ERRCODE = '42501';
            END IF;

            IF v_actor_current_revision <> v_actor_revision THEN
                RAISE EXCEPTION 'Platform authority revision is stale'
                    USING ERRCODE = '40001';
            END IF;

            IF NOT EXISTS (
                SELECT 1
                  FROM request_engine.principal_authority_grants AS grant_row
                 WHERE grant_row.principal_id = v_actor_id
                   AND grant_row.principal_plane = 'platform'
                   AND grant_row.authority_plane = 'platform'
                   AND grant_row.status = 'active'
                   AND grant_row.capability_key = p_capability
            ) THEN
                RAISE EXCEPTION
                    'Current Platform Principal lacks configuration authority'
                    USING ERRCODE = '42501';
            END IF;

            RETURN QUERY
            SELECT v_actor_id, v_actor_method, v_correlation_id;
        END
        $function$;
        """
    )

    op.execute(
        r"""
        CREATE FUNCTION request_platform.read_platform_configuration_revisions(
            p_configuration_kind text
        )
        RETURNS TABLE (
            configuration_revision_id uuid,
            configuration_kind text,
            provider_kind text,
            revision bigint,
            configuration jsonb,
            secret_binding_id uuid,
            state text,
            created_by_principal_id uuid,
            created_at timestamptz,
            validated_at timestamptz,
            activated_at timestamptz,
            disabled_at timestamptz
        )
        LANGUAGE plpgsql
        STABLE
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $function$
        BEGIN
            PERFORM 1
              FROM request_platform.assert_platform_configuration_actor(
                  'platform.configuration.read'
              );

            IF p_configuration_kind IS NOT NULL
               AND p_configuration_kind !~ '^[a-z][a-z0-9_.-]{1,79}$'
            THEN
                RAISE EXCEPTION 'Platform configuration kind is invalid'
                    USING ERRCODE = '22023';
            END IF;

            RETURN QUERY
            SELECT
                revision_row.id,
                revision_row.configuration_kind,
                revision_row.provider_kind,
                revision_row.revision,
                revision_row.configuration,
                revision_row.secret_binding_id,
                revision_row.state,
                revision_row.created_by_principal_id,
                revision_row.created_at,
                revision_row.validated_at,
                revision_row.activated_at,
                revision_row.disabled_at
              FROM request_engine.platform_configuration_revisions AS revision_row
             WHERE p_configuration_kind IS NULL
                OR revision_row.configuration_kind = p_configuration_kind
             ORDER BY
                revision_row.configuration_kind,
                revision_row.revision DESC;
        END
        $function$;

        CREATE FUNCTION request_platform.read_platform_secret_binding(
            p_binding_id uuid
        )
        RETURNS TABLE (
            binding_id uuid,
            purpose text,
            backend text,
            backend_version integer,
            status text,
            revision bigint,
            created_at timestamptz,
            rotated_at timestamptz,
            revoked_at timestamptz
        )
        LANGUAGE plpgsql
        STABLE
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $function$
        BEGIN
            PERFORM 1
              FROM request_platform.assert_platform_configuration_actor(
                  'platform.configuration.read'
              );

            RETURN QUERY
            SELECT
                binding.id,
                binding.purpose,
                binding.backend,
                binding.backend_version,
                binding.status,
                binding.revision,
                binding.created_at,
                binding.rotated_at,
                binding.revoked_at
              FROM request_engine.platform_secret_bindings AS binding
             WHERE binding.id = p_binding_id;
        END
        $function$;
        """
    )

    op.execute(
        r"""
        CREATE FUNCTION request_platform.stage_platform_configuration(
            p_configuration_kind text,
            p_provider_kind text,
            p_configuration jsonb,
            p_secret_binding_id uuid,
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
            v_revision_id uuid;
            v_revision bigint;
        BEGIN
            SELECT actor_id, actor_method, correlation_id
              INTO v_actor_id, v_actor_method, v_correlation_id
              FROM request_platform.assert_platform_configuration_actor(
                  'platform.configuration.stage'
              );

            IF p_configuration_kind !~ '^[a-z][a-z0-9_.-]{1,79}$'
               OR p_provider_kind !~ '^[a-z][a-z0-9_.-]{1,79}$'
               OR p_configuration IS NULL
               OR jsonb_typeof(p_configuration) <> 'object'
               OR p_idempotency_key_digest !~ '^[0-9a-f]{64}$'
               OR p_intent_digest !~ '^[0-9a-f]{64}$'
            THEN
                RAISE EXCEPTION 'Platform configuration stage input is invalid'
                    USING ERRCODE = '22023';
            END IF;

            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended(
                    'p7:idempotency:'
                    || v_actor_id::text
                    || ':platform.configuration.stage:'
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
               AND fact.capability_key = 'platform.configuration.stage'
               AND fact.idempotency_key_digest = p_idempotency_key_digest;

            IF FOUND THEN
                IF v_replay.intent_digest <> p_intent_digest THEN
                    RAISE EXCEPTION
                        'Idempotency key conflicts with another stage intent'
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
                    'p7:configuration-kind:' || p_configuration_kind,
                    0
                )
            );

            IF p_secret_binding_id IS NOT NULL
               AND NOT EXISTS (
                   SELECT 1
                     FROM request_engine.platform_secret_bindings AS binding
                    WHERE binding.id = p_secret_binding_id
                      AND binding.status = 'active'
               )
            THEN
                RAISE EXCEPTION 'Platform secret binding is unavailable'
                    USING ERRCODE = '23514';
            END IF;

            SELECT coalesce(max(revision_row.revision), 0) + 1
              INTO v_revision
              FROM request_engine.platform_configuration_revisions AS revision_row
             WHERE revision_row.configuration_kind = p_configuration_kind;

            v_revision_id := gen_random_uuid();

            INSERT INTO request_engine.platform_configuration_revisions (
                id,
                configuration_kind,
                provider_kind,
                revision,
                configuration,
                secret_binding_id,
                created_by_principal_id
            ) VALUES (
                v_revision_id,
                p_configuration_kind,
                p_provider_kind,
                v_revision,
                p_configuration,
                p_secret_binding_id,
                v_actor_id
            );

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
                'staged',
                v_revision_id,
                p_configuration_kind,
                v_revision,
                p_secret_binding_id,
                v_actor_id,
                v_actor_method,
                v_correlation_id,
                jsonb_build_object(
                    'provider_kind',
                    p_provider_kind,
                    'result_state',
                    'draft'
                ),
                'platform.configuration.stage',
                p_idempotency_key_digest,
                p_intent_digest
            );

            RETURN QUERY
            SELECT v_revision_id, v_revision, 'draft'::text;
        END
        $function$;
        """
    )

    op.execute(
        r"""
        CREATE FUNCTION request_platform.validate_platform_configuration(
            p_configuration_kind text,
            p_revision bigint,
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
        BEGIN
            SELECT actor_id, actor_method, correlation_id
              INTO v_actor_id, v_actor_method, v_correlation_id
              FROM request_platform.assert_platform_configuration_actor(
                  'platform.configuration.validate'
              );

            IF p_configuration_kind !~ '^[a-z][a-z0-9_.-]{1,79}$'
               OR p_revision IS NULL
               OR p_revision < 1
               OR (
                   p_expected_active_revision IS NOT NULL
                   AND p_expected_active_revision < 1
               )
               OR p_idempotency_key_digest !~ '^[0-9a-f]{64}               OR p_intent_digest !~ '^[0-9a-f]{64}$'
            THEN
                RAISE EXCEPTION 'Platform configuration validation input is invalid'
                    USING ERRCODE = '22023';
            END IF;

            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended(
                    'p7:idempotency:'
                    || v_actor_id::text
                    || ':platform.configuration.validate:'
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
                    'p7:configuration-kind:' || p_configuration_kind,
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
                RAISE EXCEPTION
                    'Platform configuration revision is not a draft'
                    USING ERRCODE = '40001';
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
                jsonb_build_object('result_state', 'validated'),
                'platform.configuration.validate',
                p_idempotency_key_digest,
                p_intent_digest
            );

            RETURN QUERY
            SELECT v_target.id, p_revision, 'validated'::text;
        END
        $function$;
        """
    )

    op.execute(
        r"""
        CREATE FUNCTION request_platform.activate_platform_configuration(
            p_configuration_kind text,
            p_revision bigint,
            p_expected_active_revision bigint,
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
            v_previous record;
        BEGIN
            SELECT actor_id, actor_method, correlation_id
              INTO v_actor_id, v_actor_method, v_correlation_id
              FROM request_platform.assert_platform_configuration_actor(
                  'platform.configuration.activate'
              );

            IF p_configuration_kind !~ '^[a-z][a-z0-9_.-]{1,79}$'
               OR p_revision IS NULL
               OR p_revision < 1
               OR p_idempotency_key_digest !~ '^[0-9a-f]{64}$'
               OR p_intent_digest !~ '^[0-9a-f]{64}$'
            THEN
                RAISE EXCEPTION 'Platform configuration activation input is invalid'
                    USING ERRCODE = '22023';
            END IF;

            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended(
                    'p7:idempotency:'
                    || v_actor_id::text
                    || ':platform.configuration.activate:'
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
               AND fact.capability_key = 'platform.configuration.activate'
               AND fact.idempotency_key_digest = p_idempotency_key_digest;

            IF FOUND THEN
                IF v_replay.intent_digest <> p_intent_digest THEN
                    RAISE EXCEPTION
                        'Idempotency key conflicts with another activation intent'
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
                    'p7:configuration-kind:' || p_configuration_kind,
                    0
                )
            );

            SELECT
                revision_row.id,
                revision_row.revision,
                revision_row.secret_binding_id
              INTO v_previous
              FROM request_engine.platform_configuration_revisions AS revision_row
             WHERE revision_row.configuration_kind = p_configuration_kind
               AND revision_row.state = 'active'
             FOR UPDATE;

            IF p_expected_active_revision IS NULL THEN
                IF FOUND THEN
                    RAISE EXCEPTION
                        'Platform configuration active revision changed'
                        USING ERRCODE = '40001';
                END IF;
            ELSIF NOT FOUND
               OR v_previous.revision <> p_expected_active_revision
            THEN
                RAISE EXCEPTION
                    'Platform configuration active revision changed'
                    USING ERRCODE = '40001';
            END IF;

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

            IF v_target.state <> 'validated' THEN
                RAISE EXCEPTION
                    'Platform configuration revision requires validation'
                    USING ERRCODE = '40001';
            END IF;

            IF v_previous.id IS NOT NULL THEN
                UPDATE request_engine.platform_configuration_revisions
                   SET state = 'superseded'
                 WHERE id = v_previous.id;

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
                    capability_key
                ) VALUES (
                    'superseded',
                    v_previous.id,
                    p_configuration_kind,
                    v_previous.revision,
                    v_previous.secret_binding_id,
                    v_actor_id,
                    v_actor_method,
                    v_correlation_id,
                    jsonb_build_object(
                        'result_state',
                        'superseded',
                        'superseded_by_revision',
                        p_revision
                    ),
                    'platform.configuration.activate'
                );
            END IF;

            UPDATE request_engine.platform_configuration_revisions
               SET state = 'active',
                   activated_at = clock_timestamp()
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
                'activated',
                v_target.id,
                p_configuration_kind,
                p_revision,
                v_target.secret_binding_id,
                v_actor_id,
                v_actor_method,
                v_correlation_id,
                jsonb_build_object(
                    'previous_active_revision',
                    p_expected_active_revision,
                    'result_state',
                    'active'
                ),
                'platform.configuration.activate',
                p_idempotency_key_digest,
                p_intent_digest
            );

            PERFORM pg_catalog.pg_notify(
                'request_engine_platform_configuration',
                jsonb_build_object(
                    'configuration_kind',
                    p_configuration_kind,
                    'revision',
                    p_revision,
                    'state',
                    'active'
                )::text
            );

            RETURN QUERY
            SELECT v_target.id, p_revision, 'active'::text;
        END
        $function$;
        """
    )

    op.execute(
        r"""
        CREATE FUNCTION request_platform.disable_platform_configuration(
            p_configuration_kind text,
            p_revision bigint,
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
        BEGIN
            SELECT actor_id, actor_method, correlation_id
              INTO v_actor_id, v_actor_method, v_correlation_id
              FROM request_platform.assert_platform_configuration_actor(
                  'platform.configuration.disable'
              );

            IF p_configuration_kind !~ '^[a-z][a-z0-9_.-]{1,79}$'
               OR p_revision IS NULL
               OR p_revision < 1
               OR p_idempotency_key_digest !~ '^[0-9a-f]{64}$'
               OR p_intent_digest !~ '^[0-9a-f]{64}$'
            THEN
                RAISE EXCEPTION 'Platform configuration disable input is invalid'
                    USING ERRCODE = '22023';
            END IF;

            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended(
                    'p7:idempotency:'
                    || v_actor_id::text
                    || ':platform.configuration.disable:'
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
               AND fact.capability_key = 'platform.configuration.disable'
               AND fact.idempotency_key_digest = p_idempotency_key_digest;

            IF FOUND THEN
                IF v_replay.intent_digest <> p_intent_digest THEN
                    RAISE EXCEPTION
                        'Idempotency key conflicts with another disable intent'
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
                    'p7:configuration-kind:' || p_configuration_kind,
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

            IF v_target.state NOT IN ('draft', 'validated', 'active') THEN
                RAISE EXCEPTION
                    'Platform configuration revision cannot be disabled'
                    USING ERRCODE = '40001';
            END IF;

            UPDATE request_engine.platform_configuration_revisions
               SET state = 'disabled',
                   disabled_at = clock_timestamp()
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
                'disabled',
                v_target.id,
                p_configuration_kind,
                p_revision,
                v_target.secret_binding_id,
                v_actor_id,
                v_actor_method,
                v_correlation_id,
                jsonb_build_object(
                    'previous_state',
                    v_target.state,
                    'result_state',
                    'disabled'
                ),
                'platform.configuration.disable',
                p_idempotency_key_digest,
                p_intent_digest
            );

            IF v_target.state = 'active' THEN
                PERFORM pg_catalog.pg_notify(
                    'request_engine_platform_configuration',
                    jsonb_build_object(
                        'configuration_kind',
                        p_configuration_kind,
                        'revision',
                        p_revision,
                        'state',
                        'disabled'
                    )::text
                );
            END IF;

            RETURN QUERY
            SELECT v_target.id, p_revision, 'disabled'::text;
        END
        $function$;
        """
    )

    op.execute(
        r"""
        CREATE FUNCTION request_platform.record_platform_secret_binding(
            p_purpose text,
            p_backend text,
            p_secret_id uuid,
            p_backend_version integer,
            p_idempotency_key_digest text,
            p_intent_digest text
        )
        RETURNS TABLE (
            binding_id uuid,
            revision bigint,
            backend_version integer,
            status text
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
            v_binding_id uuid;
        BEGIN
            SELECT actor_id, actor_method, correlation_id
              INTO v_actor_id, v_actor_method, v_correlation_id
              FROM request_platform.assert_platform_configuration_actor(
                  'platform.secret.write'
              );

            IF p_purpose !~ '^[a-z][a-z0-9_.-]{1,127}$'
               OR p_backend NOT IN ('openbao', 'vault')
               OR p_secret_id IS NULL
               OR p_backend_version IS NULL
               OR p_backend_version < 1
               OR p_idempotency_key_digest !~ '^[0-9a-f]{64}$'
               OR p_intent_digest !~ '^[0-9a-f]{64}$'
            THEN
                RAISE EXCEPTION 'Platform secret binding input is invalid'
                    USING ERRCODE = '22023';
            END IF;

            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended(
                    'p7:idempotency:'
                    || v_actor_id::text
                    || ':platform.secret.write:'
                    || p_idempotency_key_digest,
                    0
                )
            );

            SELECT
                fact.secret_binding_id,
                fact.revision,
                fact.intent_digest,
                fact.detail
              INTO v_replay
              FROM request_engine.platform_configuration_facts AS fact
             WHERE fact.actor_principal_id = v_actor_id
               AND fact.capability_key = 'platform.secret.write'
               AND fact.idempotency_key_digest = p_idempotency_key_digest;

            IF FOUND THEN
                IF v_replay.intent_digest <> p_intent_digest THEN
                    RAISE EXCEPTION
                        'Idempotency key conflicts with another secret-write intent'
                        USING ERRCODE = '23505';
                END IF;
                RETURN QUERY
                SELECT
                    v_replay.secret_binding_id,
                    v_replay.revision,
                    (v_replay.detail ->> 'backend_version')::integer,
                    v_replay.detail ->> 'result_status';
                RETURN;
            END IF;

            v_binding_id := gen_random_uuid();

            INSERT INTO request_engine.platform_secret_bindings (
                id,
                purpose,
                backend,
                secret_id,
                backend_version
            ) VALUES (
                v_binding_id,
                p_purpose,
                p_backend,
                p_secret_id,
                p_backend_version
            );

            INSERT INTO request_engine.platform_configuration_facts (
                event_kind,
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
                'secret_bound',
                NULL,
                1,
                v_binding_id,
                v_actor_id,
                v_actor_method,
                v_correlation_id,
                jsonb_build_object(
                    'purpose',
                    p_purpose,
                    'backend',
                    p_backend,
                    'backend_version',
                    p_backend_version,
                    'result_status',
                    'active'
                ),
                'platform.secret.write',
                p_idempotency_key_digest,
                p_intent_digest
            );

            RETURN QUERY
            SELECT v_binding_id, 1::bigint, p_backend_version, 'active'::text;
        END
        $function$;
        """
    )

    op.execute(
        r"""
        CREATE FUNCTION request_platform.commit_platform_secret_rotation(
            p_binding_id uuid,
            p_expected_revision bigint,
            p_expected_backend_version integer,
            p_new_backend_version integer,
            p_idempotency_key_digest text,
            p_intent_digest text
        )
        RETURNS TABLE (
            binding_id uuid,
            revision bigint,
            backend_version integer,
            status text
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
            v_binding record;
            v_revision bigint;
        BEGIN
            SELECT actor_id, actor_method, correlation_id
              INTO v_actor_id, v_actor_method, v_correlation_id
              FROM request_platform.assert_platform_configuration_actor(
                  'platform.secret.rotate'
              );

            IF p_binding_id IS NULL
               OR p_expected_revision IS NULL
               OR p_expected_revision < 1
               OR p_expected_backend_version IS NULL
               OR p_expected_backend_version < 1
               OR p_new_backend_version IS NULL
               OR p_new_backend_version <= p_expected_backend_version
               OR p_idempotency_key_digest !~ '^[0-9a-f]{64}$'
               OR p_intent_digest !~ '^[0-9a-f]{64}$'
            THEN
                RAISE EXCEPTION 'Platform secret rotation input is invalid'
                    USING ERRCODE = '22023';
            END IF;

            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended(
                    'p7:idempotency:'
                    || v_actor_id::text
                    || ':platform.secret.rotate:'
                    || p_idempotency_key_digest,
                    0
                )
            );

            SELECT
                fact.secret_binding_id,
                fact.revision,
                fact.intent_digest,
                fact.detail
              INTO v_replay
              FROM request_engine.platform_configuration_facts AS fact
             WHERE fact.actor_principal_id = v_actor_id
               AND fact.capability_key = 'platform.secret.rotate'
               AND fact.idempotency_key_digest = p_idempotency_key_digest;

            IF FOUND THEN
                IF v_replay.intent_digest <> p_intent_digest THEN
                    RAISE EXCEPTION
                        'Idempotency key conflicts with another secret-rotation intent'
                        USING ERRCODE = '23505';
                END IF;
                RETURN QUERY
                SELECT
                    v_replay.secret_binding_id,
                    v_replay.revision,
                    (v_replay.detail ->> 'backend_version')::integer,
                    v_replay.detail ->> 'result_status';
                RETURN;
            END IF;

            SELECT
                binding.id,
                binding.purpose,
                binding.backend_version,
                binding.revision,
                binding.status
              INTO v_binding
              FROM request_engine.platform_secret_bindings AS binding
             WHERE binding.id = p_binding_id
             FOR UPDATE;

            IF NOT FOUND THEN
                RAISE EXCEPTION 'Platform secret binding does not exist'
                    USING ERRCODE = 'P0002';
            END IF;

            IF v_binding.status <> 'active'
               OR v_binding.revision <> p_expected_revision
               OR v_binding.backend_version <> p_expected_backend_version
            THEN
                RAISE EXCEPTION 'Platform secret binding revision is stale'
                    USING ERRCODE = '40001';
            END IF;

            UPDATE request_engine.platform_secret_bindings
               SET backend_version = p_new_backend_version,
                   revision = revision + 1,
                   rotated_at = clock_timestamp()
             WHERE id = p_binding_id
            RETURNING revision INTO v_revision;

            INSERT INTO request_engine.platform_configuration_facts (
                event_kind,
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
                'secret_rotated',
                NULL,
                v_revision,
                p_binding_id,
                v_actor_id,
                v_actor_method,
                v_correlation_id,
                jsonb_build_object(
                    'purpose',
                    v_binding.purpose,
                    'previous_backend_version',
                    p_expected_backend_version,
                    'backend_version',
                    p_new_backend_version,
                    'result_status',
                    'active'
                ),
                'platform.secret.rotate',
                p_idempotency_key_digest,
                p_intent_digest
            );

            RETURN QUERY
            SELECT
                p_binding_id,
                v_revision,
                p_new_backend_version,
                'active'::text;
        END
        $function$;
        """
    )

    op.execute(
        r"""
        CREATE FUNCTION request_platform.revoke_platform_secret_binding(
            p_binding_id uuid,
            p_expected_revision bigint,
            p_expected_backend_version integer,
            p_idempotency_key_digest text,
            p_intent_digest text
        )
        RETURNS TABLE (
            binding_id uuid,
            revision bigint,
            backend_version integer,
            status text
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
            v_binding record;
            v_revision bigint;
        BEGIN
            SELECT actor_id, actor_method, correlation_id
              INTO v_actor_id, v_actor_method, v_correlation_id
              FROM request_platform.assert_platform_configuration_actor(
                  'platform.secret.revoke'
              );

            IF p_binding_id IS NULL
               OR p_expected_revision IS NULL
               OR p_expected_revision < 1
               OR p_expected_backend_version IS NULL
               OR p_expected_backend_version < 1
               OR p_idempotency_key_digest !~ '^[0-9a-f]{64}$'
               OR p_intent_digest !~ '^[0-9a-f]{64}$'
            THEN
                RAISE EXCEPTION 'Platform secret revocation input is invalid'
                    USING ERRCODE = '22023';
            END IF;

            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended(
                    'p7:idempotency:'
                    || v_actor_id::text
                    || ':platform.secret.revoke:'
                    || p_idempotency_key_digest,
                    0
                )
            );

            SELECT
                fact.secret_binding_id,
                fact.revision,
                fact.intent_digest,
                fact.detail
              INTO v_replay
              FROM request_engine.platform_configuration_facts AS fact
             WHERE fact.actor_principal_id = v_actor_id
               AND fact.capability_key = 'platform.secret.revoke'
               AND fact.idempotency_key_digest = p_idempotency_key_digest;

            IF FOUND THEN
                IF v_replay.intent_digest <> p_intent_digest THEN
                    RAISE EXCEPTION
                        'Idempotency key conflicts with another secret-revocation intent'
                        USING ERRCODE = '23505';
                END IF;
                RETURN QUERY
                SELECT
                    v_replay.secret_binding_id,
                    v_replay.revision,
                    (v_replay.detail ->> 'backend_version')::integer,
                    v_replay.detail ->> 'result_status';
                RETURN;
            END IF;

            SELECT
                binding.id,
                binding.purpose,
                binding.backend_version,
                binding.revision,
                binding.status
              INTO v_binding
              FROM request_engine.platform_secret_bindings AS binding
             WHERE binding.id = p_binding_id
             FOR UPDATE;

            IF NOT FOUND THEN
                RAISE EXCEPTION 'Platform secret binding does not exist'
                    USING ERRCODE = 'P0002';
            END IF;

            IF v_binding.status <> 'active'
               OR v_binding.revision <> p_expected_revision
               OR v_binding.backend_version <> p_expected_backend_version
            THEN
                RAISE EXCEPTION 'Platform secret binding revision is stale'
                    USING ERRCODE = '40001';
            END IF;

            UPDATE request_engine.platform_secret_bindings
               SET status = 'revoked',
                   revision = revision + 1,
                   revoked_at = clock_timestamp()
             WHERE id = p_binding_id
            RETURNING revision INTO v_revision;

            INSERT INTO request_engine.platform_configuration_facts (
                event_kind,
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
                'secret_revoked',
                NULL,
                v_revision,
                p_binding_id,
                v_actor_id,
                v_actor_method,
                v_correlation_id,
                jsonb_build_object(
                    'purpose',
                    v_binding.purpose,
                    'backend_version',
                    p_expected_backend_version,
                    'result_status',
                    'revoked'
                ),
                'platform.secret.revoke',
                p_idempotency_key_digest,
                p_intent_digest
            );

            RETURN QUERY
            SELECT
                p_binding_id,
                v_revision,
                p_expected_backend_version,
                'revoked'::text;
        END
        $function$;
        """
    )

    for signature in _INTERNAL_FUNCTIONS:
        op.execute(f"ALTER FUNCTION {signature} OWNER TO {_CONTROL_DEFINER}")
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
    for signature in _RUNTIME_FUNCTIONS:
        op.execute(f"ALTER FUNCTION {signature} OWNER TO {_CONTROL_DEFINER}")
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO {_RUNTIME}")
    op.execute(f"REVOKE CREATE ON SCHEMA request_platform FROM {_CONTROL_DEFINER}")


def downgrade() -> None:
    raise RuntimeError("Platform configuration governance is append-preserving; roll forward")

               OR p_intent_digest !~ '^[0-9a-f]{64}$'
            THEN
                RAISE EXCEPTION 'Platform configuration validation input is invalid'
                    USING ERRCODE = '22023';
            END IF;

            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended(
                    'p7:idempotency:'
                    || v_actor_id::text
                    || ':platform.configuration.validate:'
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
                    'p7:configuration-kind:' || p_configuration_kind,
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
                RAISE EXCEPTION
                    'Platform configuration revision is not a draft'
                    USING ERRCODE = '40001';
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
                jsonb_build_object('result_state', 'validated'),
                'platform.configuration.validate',
                p_idempotency_key_digest,
                p_intent_digest
            );

            RETURN QUERY
            SELECT v_target.id, p_revision, 'validated'::text;
        END
        $function$;
        """
    )

    op.execute(
        r"""
        CREATE FUNCTION request_platform.activate_platform_configuration(
            p_configuration_kind text,
            p_revision bigint,
            p_expected_active_revision bigint,
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
            v_previous record;
        BEGIN
            SELECT actor_id, actor_method, correlation_id
              INTO v_actor_id, v_actor_method, v_correlation_id
              FROM request_platform.assert_platform_configuration_actor(
                  'platform.configuration.activate'
              );

            IF p_configuration_kind !~ '^[a-z][a-z0-9_.-]{1,79}$'
               OR p_revision IS NULL
               OR p_revision < 1
               OR p_idempotency_key_digest !~ '^[0-9a-f]{64}$'
               OR p_intent_digest !~ '^[0-9a-f]{64}$'
            THEN
                RAISE EXCEPTION 'Platform configuration activation input is invalid'
                    USING ERRCODE = '22023';
            END IF;

            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended(
                    'p7:idempotency:'
                    || v_actor_id::text
                    || ':platform.configuration.activate:'
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
               AND fact.capability_key = 'platform.configuration.activate'
               AND fact.idempotency_key_digest = p_idempotency_key_digest;

            IF FOUND THEN
                IF v_replay.intent_digest <> p_intent_digest THEN
                    RAISE EXCEPTION
                        'Idempotency key conflicts with another activation intent'
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
                    'p7:configuration-kind:' || p_configuration_kind,
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

            IF v_target.state <> 'validated' THEN
                RAISE EXCEPTION
                    'Platform configuration revision requires validation'
                    USING ERRCODE = '40001';
            END IF;

            SELECT
                revision_row.id,
                revision_row.revision,
                revision_row.secret_binding_id
              INTO v_previous
              FROM request_engine.platform_configuration_revisions AS revision_row
             WHERE revision_row.configuration_kind = p_configuration_kind
               AND revision_row.state = 'active'
             FOR UPDATE;

            IF FOUND THEN
                UPDATE request_engine.platform_configuration_revisions
                   SET state = 'superseded'
                 WHERE id = v_previous.id;

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
                    capability_key
                ) VALUES (
                    'superseded',
                    v_previous.id,
                    p_configuration_kind,
                    v_previous.revision,
                    v_previous.secret_binding_id,
                    v_actor_id,
                    v_actor_method,
                    v_correlation_id,
                    jsonb_build_object(
                        'result_state',
                        'superseded',
                        'superseded_by_revision',
                        p_revision
                    ),
                    'platform.configuration.activate'
                );
            END IF;

            UPDATE request_engine.platform_configuration_revisions
               SET state = 'active',
                   activated_at = clock_timestamp()
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
                'activated',
                v_target.id,
                p_configuration_kind,
                p_revision,
                v_target.secret_binding_id,
                v_actor_id,
                v_actor_method,
                v_correlation_id,
                jsonb_build_object('result_state', 'active'),
                'platform.configuration.activate',
                p_idempotency_key_digest,
                p_intent_digest
            );

            PERFORM pg_catalog.pg_notify(
                'request_engine_platform_configuration',
                jsonb_build_object(
                    'configuration_kind',
                    p_configuration_kind,
                    'revision',
                    p_revision,
                    'state',
                    'active'
                )::text
            );

            RETURN QUERY
            SELECT v_target.id, p_revision, 'active'::text;
        END
        $function$;
        """
    )

    op.execute(
        r"""
        CREATE FUNCTION request_platform.disable_platform_configuration(
            p_configuration_kind text,
            p_revision bigint,
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
        BEGIN
            SELECT actor_id, actor_method, correlation_id
              INTO v_actor_id, v_actor_method, v_correlation_id
              FROM request_platform.assert_platform_configuration_actor(
                  'platform.configuration.disable'
              );

            IF p_configuration_kind !~ '^[a-z][a-z0-9_.-]{1,79}$'
               OR p_revision IS NULL
               OR p_revision < 1
               OR p_idempotency_key_digest !~ '^[0-9a-f]{64}$'
               OR p_intent_digest !~ '^[0-9a-f]{64}$'
            THEN
                RAISE EXCEPTION 'Platform configuration disable input is invalid'
                    USING ERRCODE = '22023';
            END IF;

            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended(
                    'p7:idempotency:'
                    || v_actor_id::text
                    || ':platform.configuration.disable:'
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
               AND fact.capability_key = 'platform.configuration.disable'
               AND fact.idempotency_key_digest = p_idempotency_key_digest;

            IF FOUND THEN
                IF v_replay.intent_digest <> p_intent_digest THEN
                    RAISE EXCEPTION
                        'Idempotency key conflicts with another disable intent'
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
                    'p7:configuration-kind:' || p_configuration_kind,
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

            IF v_target.state NOT IN ('draft', 'validated', 'active') THEN
                RAISE EXCEPTION
                    'Platform configuration revision cannot be disabled'
                    USING ERRCODE = '40001';
            END IF;

            UPDATE request_engine.platform_configuration_revisions
               SET state = 'disabled',
                   disabled_at = clock_timestamp()
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
                'disabled',
                v_target.id,
                p_configuration_kind,
                p_revision,
                v_target.secret_binding_id,
                v_actor_id,
                v_actor_method,
                v_correlation_id,
                jsonb_build_object(
                    'previous_state',
                    v_target.state,
                    'result_state',
                    'disabled'
                ),
                'platform.configuration.disable',
                p_idempotency_key_digest,
                p_intent_digest
            );

            IF v_target.state = 'active' THEN
                PERFORM pg_catalog.pg_notify(
                    'request_engine_platform_configuration',
                    jsonb_build_object(
                        'configuration_kind',
                        p_configuration_kind,
                        'revision',
                        p_revision,
                        'state',
                        'disabled'
                    )::text
                );
            END IF;

            RETURN QUERY
            SELECT v_target.id, p_revision, 'disabled'::text;
        END
        $function$;
        """
    )

    op.execute(
        r"""
        CREATE FUNCTION request_platform.record_platform_secret_binding(
            p_purpose text,
            p_backend text,
            p_secret_id uuid,
            p_backend_version integer,
            p_idempotency_key_digest text,
            p_intent_digest text
        )
        RETURNS TABLE (
            binding_id uuid,
            revision bigint,
            backend_version integer,
            status text
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
            v_binding_id uuid;
        BEGIN
            SELECT actor_id, actor_method, correlation_id
              INTO v_actor_id, v_actor_method, v_correlation_id
              FROM request_platform.assert_platform_configuration_actor(
                  'platform.secret.write'
              );

            IF p_purpose !~ '^[a-z][a-z0-9_.-]{1,127}$'
               OR p_backend NOT IN ('openbao', 'vault')
               OR p_secret_id IS NULL
               OR p_backend_version IS NULL
               OR p_backend_version < 1
               OR p_idempotency_key_digest !~ '^[0-9a-f]{64}$'
               OR p_intent_digest !~ '^[0-9a-f]{64}$'
            THEN
                RAISE EXCEPTION 'Platform secret binding input is invalid'
                    USING ERRCODE = '22023';
            END IF;

            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended(
                    'p7:idempotency:'
                    || v_actor_id::text
                    || ':platform.secret.write:'
                    || p_idempotency_key_digest,
                    0
                )
            );

            SELECT
                fact.secret_binding_id,
                fact.revision,
                fact.intent_digest,
                fact.detail
              INTO v_replay
              FROM request_engine.platform_configuration_facts AS fact
             WHERE fact.actor_principal_id = v_actor_id
               AND fact.capability_key = 'platform.secret.write'
               AND fact.idempotency_key_digest = p_idempotency_key_digest;

            IF FOUND THEN
                IF v_replay.intent_digest <> p_intent_digest THEN
                    RAISE EXCEPTION
                        'Idempotency key conflicts with another secret-write intent'
                        USING ERRCODE = '23505';
                END IF;
                RETURN QUERY
                SELECT
                    v_replay.secret_binding_id,
                    v_replay.revision,
                    (v_replay.detail ->> 'backend_version')::integer,
                    v_replay.detail ->> 'result_status';
                RETURN;
            END IF;

            v_binding_id := gen_random_uuid();

            INSERT INTO request_engine.platform_secret_bindings (
                id,
                purpose,
                backend,
                secret_id,
                backend_version
            ) VALUES (
                v_binding_id,
                p_purpose,
                p_backend,
                p_secret_id,
                p_backend_version
            );

            INSERT INTO request_engine.platform_configuration_facts (
                event_kind,
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
                'secret_bound',
                NULL,
                1,
                v_binding_id,
                v_actor_id,
                v_actor_method,
                v_correlation_id,
                jsonb_build_object(
                    'purpose',
                    p_purpose,
                    'backend',
                    p_backend,
                    'backend_version',
                    p_backend_version,
                    'result_status',
                    'active'
                ),
                'platform.secret.write',
                p_idempotency_key_digest,
                p_intent_digest
            );

            RETURN QUERY
            SELECT v_binding_id, 1::bigint, p_backend_version, 'active'::text;
        END
        $function$;
        """
    )

    op.execute(
        r"""
        CREATE FUNCTION request_platform.commit_platform_secret_rotation(
            p_binding_id uuid,
            p_expected_revision bigint,
            p_expected_backend_version integer,
            p_new_backend_version integer,
            p_idempotency_key_digest text,
            p_intent_digest text
        )
        RETURNS TABLE (
            binding_id uuid,
            revision bigint,
            backend_version integer,
            status text
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
            v_binding record;
            v_revision bigint;
        BEGIN
            SELECT actor_id, actor_method, correlation_id
              INTO v_actor_id, v_actor_method, v_correlation_id
              FROM request_platform.assert_platform_configuration_actor(
                  'platform.secret.rotate'
              );

            IF p_binding_id IS NULL
               OR p_expected_revision IS NULL
               OR p_expected_revision < 1
               OR p_expected_backend_version IS NULL
               OR p_expected_backend_version < 1
               OR p_new_backend_version IS NULL
               OR p_new_backend_version <= p_expected_backend_version
               OR p_idempotency_key_digest !~ '^[0-9a-f]{64}$'
               OR p_intent_digest !~ '^[0-9a-f]{64}$'
            THEN
                RAISE EXCEPTION 'Platform secret rotation input is invalid'
                    USING ERRCODE = '22023';
            END IF;

            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended(
                    'p7:idempotency:'
                    || v_actor_id::text
                    || ':platform.secret.rotate:'
                    || p_idempotency_key_digest,
                    0
                )
            );

            SELECT
                fact.secret_binding_id,
                fact.revision,
                fact.intent_digest,
                fact.detail
              INTO v_replay
              FROM request_engine.platform_configuration_facts AS fact
             WHERE fact.actor_principal_id = v_actor_id
               AND fact.capability_key = 'platform.secret.rotate'
               AND fact.idempotency_key_digest = p_idempotency_key_digest;

            IF FOUND THEN
                IF v_replay.intent_digest <> p_intent_digest THEN
                    RAISE EXCEPTION
                        'Idempotency key conflicts with another secret-rotation intent'
                        USING ERRCODE = '23505';
                END IF;
                RETURN QUERY
                SELECT
                    v_replay.secret_binding_id,
                    v_replay.revision,
                    (v_replay.detail ->> 'backend_version')::integer,
                    v_replay.detail ->> 'result_status';
                RETURN;
            END IF;

            SELECT
                binding.id,
                binding.purpose,
                binding.backend_version,
                binding.revision,
                binding.status
              INTO v_binding
              FROM request_engine.platform_secret_bindings AS binding
             WHERE binding.id = p_binding_id
             FOR UPDATE;

            IF NOT FOUND THEN
                RAISE EXCEPTION 'Platform secret binding does not exist'
                    USING ERRCODE = 'P0002';
            END IF;

            IF v_binding.status <> 'active'
               OR v_binding.revision <> p_expected_revision
               OR v_binding.backend_version <> p_expected_backend_version
            THEN
                RAISE EXCEPTION 'Platform secret binding revision is stale'
                    USING ERRCODE = '40001';
            END IF;

            UPDATE request_engine.platform_secret_bindings
               SET backend_version = p_new_backend_version,
                   revision = revision + 1,
                   rotated_at = clock_timestamp()
             WHERE id = p_binding_id
            RETURNING revision INTO v_revision;

            INSERT INTO request_engine.platform_configuration_facts (
                event_kind,
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
                'secret_rotated',
                NULL,
                v_revision,
                p_binding_id,
                v_actor_id,
                v_actor_method,
                v_correlation_id,
                jsonb_build_object(
                    'purpose',
                    v_binding.purpose,
                    'previous_backend_version',
                    p_expected_backend_version,
                    'backend_version',
                    p_new_backend_version,
                    'result_status',
                    'active'
                ),
                'platform.secret.rotate',
                p_idempotency_key_digest,
                p_intent_digest
            );

            RETURN QUERY
            SELECT
                p_binding_id,
                v_revision,
                p_new_backend_version,
                'active'::text;
        END
        $function$;
        """
    )

    op.execute(
        r"""
        CREATE FUNCTION request_platform.revoke_platform_secret_binding(
            p_binding_id uuid,
            p_expected_revision bigint,
            p_expected_backend_version integer,
            p_idempotency_key_digest text,
            p_intent_digest text
        )
        RETURNS TABLE (
            binding_id uuid,
            revision bigint,
            backend_version integer,
            status text
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
            v_binding record;
            v_revision bigint;
        BEGIN
            SELECT actor_id, actor_method, correlation_id
              INTO v_actor_id, v_actor_method, v_correlation_id
              FROM request_platform.assert_platform_configuration_actor(
                  'platform.secret.revoke'
              );

            IF p_binding_id IS NULL
               OR p_expected_revision IS NULL
               OR p_expected_revision < 1
               OR p_expected_backend_version IS NULL
               OR p_expected_backend_version < 1
               OR p_idempotency_key_digest !~ '^[0-9a-f]{64}$'
               OR p_intent_digest !~ '^[0-9a-f]{64}$'
            THEN
                RAISE EXCEPTION 'Platform secret revocation input is invalid'
                    USING ERRCODE = '22023';
            END IF;

            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended(
                    'p7:idempotency:'
                    || v_actor_id::text
                    || ':platform.secret.revoke:'
                    || p_idempotency_key_digest,
                    0
                )
            );

            SELECT
                fact.secret_binding_id,
                fact.revision,
                fact.intent_digest,
                fact.detail
              INTO v_replay
              FROM request_engine.platform_configuration_facts AS fact
             WHERE fact.actor_principal_id = v_actor_id
               AND fact.capability_key = 'platform.secret.revoke'
               AND fact.idempotency_key_digest = p_idempotency_key_digest;

            IF FOUND THEN
                IF v_replay.intent_digest <> p_intent_digest THEN
                    RAISE EXCEPTION
                        'Idempotency key conflicts with another secret-revocation intent'
                        USING ERRCODE = '23505';
                END IF;
                RETURN QUERY
                SELECT
                    v_replay.secret_binding_id,
                    v_replay.revision,
                    (v_replay.detail ->> 'backend_version')::integer,
                    v_replay.detail ->> 'result_status';
                RETURN;
            END IF;

            SELECT
                binding.id,
                binding.purpose,
                binding.backend_version,
                binding.revision,
                binding.status
              INTO v_binding
              FROM request_engine.platform_secret_bindings AS binding
             WHERE binding.id = p_binding_id
             FOR UPDATE;

            IF NOT FOUND THEN
                RAISE EXCEPTION 'Platform secret binding does not exist'
                    USING ERRCODE = 'P0002';
            END IF;

            IF v_binding.status <> 'active'
               OR v_binding.revision <> p_expected_revision
               OR v_binding.backend_version <> p_expected_backend_version
            THEN
                RAISE EXCEPTION 'Platform secret binding revision is stale'
                    USING ERRCODE = '40001';
            END IF;

            UPDATE request_engine.platform_secret_bindings
               SET status = 'revoked',
                   revision = revision + 1,
                   revoked_at = clock_timestamp()
             WHERE id = p_binding_id
            RETURNING revision INTO v_revision;

            INSERT INTO request_engine.platform_configuration_facts (
                event_kind,
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
                'secret_revoked',
                NULL,
                v_revision,
                p_binding_id,
                v_actor_id,
                v_actor_method,
                v_correlation_id,
                jsonb_build_object(
                    'purpose',
                    v_binding.purpose,
                    'backend_version',
                    p_expected_backend_version,
                    'result_status',
                    'revoked'
                ),
                'platform.secret.revoke',
                p_idempotency_key_digest,
                p_intent_digest
            );

            RETURN QUERY
            SELECT
                p_binding_id,
                v_revision,
                p_expected_backend_version,
                'revoked'::text;
        END
        $function$;
        """
    )

    for signature in _INTERNAL_FUNCTIONS:
        op.execute(f"ALTER FUNCTION {signature} OWNER TO {_CONTROL_DEFINER}")
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
    for signature in _RUNTIME_FUNCTIONS:
        op.execute(f"ALTER FUNCTION {signature} OWNER TO {_CONTROL_DEFINER}")
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO {_RUNTIME}")
    op.execute(f"REVOKE CREATE ON SCHEMA request_platform FROM {_CONTROL_DEFINER}")


def downgrade() -> None:
    raise RuntimeError("Platform configuration governance is append-preserving; roll forward")
