"""Governed global disable of a native identity (plan D3).

Adds the private platform reader for native identities and the terminal global
disable command. The command takes the identity-topology gate EXCLUSIVE with a
bounded ``lock_timeout`` containment, revalidates the platform actor, disables
the native identity and revokes its credentials, sessions and pending recovery
intents, then proves every affected tenant and the platform plane retain an
effective controller. Native bindings, grants and provenance remain historical
facts; the identity is never re-enabled.

The capability ``platform.identity.disable`` is registered in Python; existing
platform controllers receive the bootstrap grant here, mirroring the governed
recovery propagation. New roots still need the explicit controller-policy
upgrade ceremony tracked by plan E1.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0047_native_identity_disable"
down_revision: str | Sequence[str] | None = "0046_identity_binding_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(
        r"""
        CREATE OR REPLACE FUNCTION request_engine.assert_organization_has_controller(
            p_organization_id uuid
        ) RETURNS void
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $$
        DECLARE
            v_candidate uuid;
        BEGIN
            SELECT membership.principal_id
              INTO v_candidate
              FROM request_engine.staff_memberships AS membership
             WHERE membership.organization_id = p_organization_id
               AND membership.status = 'active'
               AND request_engine.principal_is_effective_tenant_controller(
                       p_organization_id, membership.principal_id)
             ORDER BY membership.principal_id
             LIMIT 1;
            IF v_candidate IS NULL THEN
                RAISE EXCEPTION 'Tenant must retain an active recovery-capable controller'
                    USING ERRCODE = '23514';
            END IF;
        END
        $$;
        ALTER FUNCTION request_engine.assert_organization_has_controller(uuid)
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_engine.assert_organization_has_controller(uuid)
            FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_engine.assert_organization_has_controller(uuid)
            TO request_platform_control_definer;

        CREATE OR REPLACE FUNCTION request_platform.assert_platform_has_controller()
        RETURNS void
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $$
        DECLARE
            v_candidate uuid;
        BEGIN
            SELECT principal.id
              INTO v_candidate
              FROM request_engine.principals AS principal
             WHERE principal.principal_plane = 'platform'
               AND request_platform.principal_is_effective_platform_controller(
                       principal.id)
             ORDER BY principal.id
             LIMIT 1;
            IF v_candidate IS NULL THEN
                RAISE EXCEPTION 'Platform must retain an effective controller'
                    USING ERRCODE = '23514';
            END IF;
        END
        $$;
        ALTER FUNCTION request_platform.assert_platform_has_controller()
            OWNER TO request_platform_control_definer;
        REVOKE ALL ON FUNCTION request_platform.assert_platform_has_controller()
            FROM PUBLIC;
        """
    )
    op.execute(
        r"""
        CREATE TABLE request_engine.platform_identity_disable_facts (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            actor_principal_id uuid NOT NULL
                REFERENCES request_engine.principals(id),
            capability_key text NOT NULL,
            native_identity_id uuid NOT NULL,
            native_authority_id uuid NOT NULL,
            revision_before bigint NOT NULL,
            revision_after bigint NOT NULL,
            reason_code text NOT NULL,
            external_case_reference text,
            affected_tenant_count integer NOT NULL,
            affected_platform boolean NOT NULL,
            idempotency_key_digest text NOT NULL,
            intent_digest text NOT NULL,
            correlation_id uuid,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            CONSTRAINT platform_identity_disable_facts_capability_check
                CHECK (capability_key = 'platform.identity.disable'),
            CONSTRAINT platform_identity_disable_facts_revision_check
                CHECK (revision_after = revision_before + 1),
            CONSTRAINT platform_identity_disable_facts_reason_check
                CHECK (length(btrim(reason_code)) BETWEEN 1 AND 80),
            CONSTRAINT platform_identity_disable_facts_key_digest_check
                CHECK (idempotency_key_digest ~ '^[0-9a-f]{64}$'),
            CONSTRAINT platform_identity_disable_facts_intent_digest_check
                CHECK (intent_digest ~ '^[0-9a-f]{64}$'),
            CONSTRAINT platform_identity_disable_facts_tenant_count_check
                CHECK (affected_tenant_count >= 0)
        );
        ALTER TABLE request_engine.platform_identity_disable_facts
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON request_engine.platform_identity_disable_facts FROM PUBLIC;
        CREATE UNIQUE INDEX platform_identity_disable_facts_idempotency_uq
            ON request_engine.platform_identity_disable_facts
            (actor_principal_id, capability_key, idempotency_key_digest);
        GRANT SELECT (id, actor_principal_id, capability_key, native_identity_id,
                      revision_after, affected_tenant_count, affected_platform,
                      idempotency_key_digest, intent_digest),
              INSERT (actor_principal_id, capability_key, native_identity_id,
                      native_authority_id, revision_before, revision_after,
                      reason_code, external_case_reference, affected_tenant_count,
                      affected_platform, idempotency_key_digest, intent_digest,
                      correlation_id)
            ON request_engine.platform_identity_disable_facts
            TO request_platform_control_definer;
        """
    )
    op.execute(
        r"""
        GRANT SELECT (id, identity_authority_id, status, revision, created_at, disabled_at)
            ON request_engine.native_identities TO request_platform_definer;

        CREATE OR REPLACE FUNCTION request_platform.read_native_identities(
            p_identity_id uuid,
            p_after uuid,
            p_limit integer
        ) RETURNS TABLE (
            native_identity_id uuid,
            identity_authority_id uuid,
            status text,
            revision bigint,
            created_at timestamp with time zone,
            disabled_at timestamp with time zone
        )
        LANGUAGE plpgsql
        STABLE
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $$
        BEGIN
            IF p_limit IS NULL OR p_limit < 1 OR p_limit > 100 THEN
                RAISE EXCEPTION 'Native identity page limit must be between 1 and 100'
                    USING ERRCODE = '22023';
            END IF;
            RETURN QUERY
            SELECT identity.id,
                   identity.identity_authority_id,
                   identity.status,
                   identity.revision,
                   identity.created_at,
                   identity.disabled_at
              FROM request_engine.native_identities AS identity
             WHERE (p_identity_id IS NULL OR identity.id = p_identity_id)
               AND (p_after IS NULL OR identity.id > p_after)
             ORDER BY identity.id
             LIMIT p_limit;
        END
        $$;
        ALTER FUNCTION request_platform.read_native_identities(uuid, uuid, integer)
            OWNER TO request_platform_definer;
        REVOKE ALL ON FUNCTION request_platform.read_native_identities(uuid, uuid, integer)
            FROM PUBLIC;
        """
    )
    op.execute(
        r"""
        GRANT SELECT (id, identity_authority_id, status, revision, session_epoch,
                      disabled_at, updated_at),
              UPDATE (status, session_epoch, revision, updated_at, disabled_at)
            ON request_engine.native_identities TO request_platform_control_definer;
        GRANT SELECT (native_identity_id, status, revision),
              UPDATE (status, revision, revoked_at)
            ON request_engine.native_credentials TO request_platform_control_definer;
        GRANT SELECT (native_identity_id, status),
              UPDATE (status, revoked_at, revocation_reason)
            ON request_engine.native_sessions TO request_platform_control_definer;
        GRANT SELECT (native_identity_id, status),
              UPDATE (status, revoked_at)
            ON request_engine.native_recovery_intents TO request_platform_control_definer;
        GRANT SELECT (id, kind, status) ON request_engine.identity_authorities
            TO request_platform_control_definer;
        GRANT EXECUTE ON FUNCTION
            request_engine.principal_is_effective_tenant_controller(uuid, uuid)
            TO request_platform_control_definer;
        """
    )
    op.execute(
        r"""
        CREATE OR REPLACE FUNCTION request_platform.disable_native_identity(
            p_native_identity_id uuid,
            p_expected_revision bigint,
            p_reason_code text,
            p_external_case_reference text,
            p_idempotency_key_digest text,
            p_intent_digest text
        ) RETURNS TABLE (
            fact_id uuid,
            native_identity_id uuid,
            revision_after bigint,
            affected_tenant_count integer,
            affected_platform boolean
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $$
        DECLARE
            v_actor_id uuid;
            v_actor_revision bigint;
            v_actor_method text;
            v_actor_kind text;
            v_actor_active boolean;
            v_actor_current_revision bigint;
            v_correlation_id uuid;
            v_identity record;
            v_binding record;
            v_authority_kind text;
            v_authority_status text;
            v_revision_before bigint;
            v_org_ids uuid[];
            v_org_id uuid;
            v_affected_platform boolean := false;
            v_affected_tenants integer := 0;
            v_replay record;
            v_fact_id uuid;
        BEGIN
            PERFORM set_config('lock_timeout', '10s', true);
            PERFORM request_engine.acquire_identity_topology_exclusive();

            IF p_native_identity_id IS NULL
               OR p_expected_revision IS NULL
               OR p_expected_revision < 1 THEN
                RAISE EXCEPTION 'Native identity and expected revision are required'
                    USING ERRCODE = '22023';
            END IF;
            IF p_reason_code IS NULL
               OR length(btrim(p_reason_code)) NOT BETWEEN 1 AND 80
               OR (p_external_case_reference IS NOT NULL
                   AND length(btrim(p_external_case_reference)) NOT BETWEEN 1 AND 200)
               OR p_idempotency_key_digest !~ '^[0-9a-f]{64}$'
               OR p_intent_digest !~ '^[0-9a-f]{64}$' THEN
                RAISE EXCEPTION 'Disable reason, case reference or digests are invalid'
                    USING ERRCODE = '22023';
            END IF;

            BEGIN
                v_actor_id := NULLIF(current_setting(
                    'request_engine.authenticated_principal_id', true
                ), '')::uuid;
                v_actor_revision := NULLIF(current_setting(
                    'request_engine.authority_revision', true
                ), '')::bigint;
                v_actor_method := NULLIF(current_setting(
                    'request_engine.authentication_method', true
                ), '');
                v_correlation_id := NULLIF(current_setting(
                    'request_engine.correlation_id', true
                ), '')::uuid;
            EXCEPTION WHEN invalid_text_representation THEN
                RAISE EXCEPTION 'Platform actor provenance is malformed'
                    USING ERRCODE = '28000';
            END;
            IF v_actor_id IS NULL OR v_actor_revision IS NULL OR v_actor_method IS NULL THEN
                RAISE EXCEPTION 'Platform actor provenance is required'
                    USING ERRCODE = '28000';
            END IF;

            -- Platform-plane serialization root: lock the platform Principal set in
            -- id order before bindings, grants or facts.
            PERFORM principal.id
              FROM request_engine.principals AS principal
             WHERE principal.principal_plane = 'platform'
             ORDER BY principal.id
             FOR UPDATE;

            SELECT principal.principal_kind, principal.active,
                   principal.authority_revision
              INTO v_actor_kind, v_actor_active, v_actor_current_revision
              FROM request_engine.principals AS principal
             WHERE principal.id = v_actor_id
               AND principal.principal_plane = 'platform';
            IF NOT FOUND OR NOT v_actor_active OR v_actor_kind <> 'human' THEN
                RAISE EXCEPTION 'Current Platform Principal cannot disable identities'
                    USING ERRCODE = '42501';
            END IF;
            IF v_actor_current_revision <> v_actor_revision THEN
                RAISE EXCEPTION 'Platform authority revision is stale'
                    USING ERRCODE = '40001';
            END IF;
            IF NOT EXISTS (
                SELECT 1
                  FROM request_engine.principal_authority_grants AS actor_grant
                 WHERE actor_grant.principal_id = v_actor_id
                   AND actor_grant.principal_plane = 'platform'
                   AND actor_grant.authority_plane = 'platform'
                   AND actor_grant.status = 'active'
                   AND actor_grant.capability_key = 'platform.identity.disable'
            ) THEN
                RAISE EXCEPTION 'Current Platform Principal lacks identity disable authority'
                    USING ERRCODE = '42501';
            END IF;

            -- Replay is evaluated only after revalidating current actor authority.
            SELECT fact.id, fact.native_identity_id, fact.revision_after,
                   fact.affected_tenant_count, fact.affected_platform,
                   fact.intent_digest
              INTO v_replay
              FROM request_engine.platform_identity_disable_facts AS fact
             WHERE fact.actor_principal_id = v_actor_id
               AND fact.capability_key = 'platform.identity.disable'
               AND fact.idempotency_key_digest = p_idempotency_key_digest;
            IF FOUND THEN
                IF v_replay.intent_digest <> p_intent_digest THEN
                    RAISE EXCEPTION 'Idempotency key was used with a different intent'
                        USING ERRCODE = '40001';
                END IF;
                RETURN QUERY SELECT v_replay.id, v_replay.native_identity_id,
                                    v_replay.revision_after,
                                    v_replay.affected_tenant_count,
                                    v_replay.affected_platform;
                RETURN;
            END IF;

            SELECT identity.id, identity.identity_authority_id,
                   identity.status, identity.revision
              INTO v_identity
              FROM request_engine.native_identities AS identity
             WHERE identity.id = p_native_identity_id
             FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Native identity not found' USING ERRCODE = 'P0002';
            END IF;
            IF v_identity.status <> 'active' THEN
                RAISE EXCEPTION 'Native identity is already disabled or terminal'
                    USING ERRCODE = '55000';
            END IF;
            IF v_identity.revision <> p_expected_revision THEN
                RAISE EXCEPTION 'Native identity revision is stale'
                    USING ERRCODE = '40001';
            END IF;
            v_revision_before := v_identity.revision;

            SELECT authority.kind, authority.status
              INTO v_authority_kind, v_authority_status
              FROM request_engine.identity_authorities AS authority
             WHERE authority.id = v_identity.identity_authority_id;
            IF NOT FOUND OR v_authority_kind <> 'native' OR v_authority_status <> 'active' THEN
                RAISE EXCEPTION 'Native identity authority is not active native'
                    USING ERRCODE = '23514';
            END IF;

            -- Only tenants whose continuity currently depends on this identity need a
            -- post-disable controller proof. The tenant predicate is owner-executed
            -- over FORCE RLS tables, so the trusted tenant GUC is set per candidate.
            FOR v_binding IN
                SELECT DISTINCT binding.organization_id, binding.principal_id
                  FROM request_engine.identity_bindings AS binding
                 WHERE binding.identity_authority_id = v_identity.identity_authority_id
                   AND binding.subject_id = p_native_identity_id::text
                   AND binding.principal_plane = 'tenant'
                   AND binding.organization_id IS NOT NULL
                   AND binding.status = 'active'
            LOOP
                PERFORM set_config(
                    'request_engine.organization_id', v_binding.organization_id::text, true
                );
                IF request_engine.principal_is_effective_tenant_controller(
                       v_binding.organization_id, v_binding.principal_id) THEN
                    v_org_ids := array_append(v_org_ids, v_binding.organization_id);
                END IF;
            END LOOP;
            PERFORM set_config('request_engine.organization_id', '', true);
            v_org_ids := (
                SELECT array_agg(DISTINCT org)
                  FROM unnest(v_org_ids) AS org
            );
            v_affected_tenants := COALESCE(array_length(v_org_ids, 1), 0);

            SELECT EXISTS (
                SELECT 1
                  FROM request_engine.identity_bindings AS binding
                 WHERE binding.identity_authority_id = v_identity.identity_authority_id
                   AND binding.subject_id = p_native_identity_id::text
                   AND binding.principal_plane = 'platform'
                   AND binding.status = 'active'
                   AND request_platform.principal_is_effective_platform_controller(
                           binding.principal_id)
            ) INTO v_affected_platform;

            UPDATE request_engine.native_identities
               SET status = 'disabled',
                   session_epoch = session_epoch + 1,
                   revision = revision + 1,
                   updated_at = clock_timestamp(),
                   disabled_at = clock_timestamp()
             WHERE id = p_native_identity_id;
            UPDATE request_engine.native_credentials AS credential
               SET status = 'revoked',
                   revision = credential.revision + 1,
                   revoked_at = clock_timestamp()
             WHERE credential.native_identity_id = p_native_identity_id
               AND credential.status = 'active';
            UPDATE request_engine.native_sessions AS session
               SET status = 'revoked',
                   revoked_at = clock_timestamp(),
                   revocation_reason = 'identity_disabled'
             WHERE session.native_identity_id = p_native_identity_id
               AND session.status = 'active';
            UPDATE request_engine.native_recovery_intents AS intent
               SET status = 'revoked',
                   revoked_at = clock_timestamp()
             WHERE intent.native_identity_id = p_native_identity_id
               AND intent.status = 'pending';

            IF v_org_ids IS NOT NULL THEN
                FOREACH v_org_id IN ARRAY v_org_ids LOOP
                    PERFORM set_config(
                        'request_engine.organization_id', v_org_id::text, true
                    );
                    PERFORM request_engine.assert_organization_has_controller(v_org_id);
                END LOOP;
                PERFORM set_config('request_engine.organization_id', '', true);
            END IF;
            IF v_affected_platform THEN
                PERFORM request_platform.assert_platform_has_controller();
            END IF;

            INSERT INTO request_engine.platform_identity_disable_facts (
                actor_principal_id, capability_key, native_identity_id,
                native_authority_id, revision_before, revision_after, reason_code,
                external_case_reference, affected_tenant_count, affected_platform,
                idempotency_key_digest, intent_digest, correlation_id
            ) VALUES (
                v_actor_id, 'platform.identity.disable', p_native_identity_id,
                v_identity.identity_authority_id, v_revision_before,
                v_revision_before + 1, btrim(p_reason_code),
                NULLIF(btrim(p_external_case_reference), ''),
                v_affected_tenants, v_affected_platform,
                p_idempotency_key_digest, p_intent_digest, v_correlation_id
            ) RETURNING id INTO v_fact_id;

            RETURN QUERY SELECT v_fact_id, p_native_identity_id,
                                v_revision_before + 1, v_affected_tenants,
                                v_affected_platform;
        END
        $$;
        ALTER FUNCTION request_platform.disable_native_identity(
            uuid, bigint, text, text, text, text
        ) OWNER TO request_platform_control_definer;
        REVOKE ALL ON FUNCTION request_platform.disable_native_identity(
            uuid, bigint, text, text, text, text
        ) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_platform.disable_native_identity(
            uuid, bigint, text, text, text, text
        ) TO request_platform_control;
        """
    )
    op.execute(
        """
        INSERT INTO request_engine.principal_authority_grants (
            principal_id, principal_plane, authority_plane, capability_key,
            delegable, provenance_kind, provenance_reference
        )
        SELECT DISTINCT controller.id,
               'platform',
               'platform',
               'platform.identity.disable',
               false,
               'trust_bootstrap',
               'platform-controller-policy-v1-identity-disable:' || controller.id::text
          FROM request_engine.principals AS controller
          JOIN request_engine.principal_authority_grants AS control_grant
            ON control_grant.principal_id = controller.id
           AND control_grant.principal_plane = 'platform'
           AND control_grant.authority_plane = 'platform'
           AND control_grant.capability_key = 'platform.tenant_provisioner.provision'
           AND control_grant.status = 'active'
         WHERE controller.principal_plane = 'platform'
           AND controller.active
           AND NOT EXISTS (
               SELECT 1
                 FROM request_engine.principal_authority_grants AS existing
                WHERE existing.principal_id = controller.id
                  AND existing.capability_key = 'platform.identity.disable'
                  AND existing.status = 'active'
           )
        """
    )


def downgrade() -> None:
    raise RuntimeError("Do not remove governed native identity disable; roll forward")
