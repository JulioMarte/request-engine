"""Governed additional Platform Owner provisioning and lifecycle.

Revision ID: 0071_platform_owner_lifecycle
Revises: 0070_offline_recovery_lock_order

P5 establishes a distinct Platform Owner authority instead of overloading the
bounded tenant-provisioner role. A new owner can be promoted only from an active
native HUMAN identity that already has an active password, a verified active
WebAuthn credential, and an active recovery-code set with at least one unused
code. Owner lifecycle changes preserve at least one effective owner.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0071_platform_owner_lifecycle"
down_revision: str | Sequence[str] | None = "0070_offline_recovery_lock_order"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONTROL_DEFINER = "request_platform_control_definer"
_RUNTIME = "request_platform_control"

_PROVISION = (
    "request_platform.provision_native_platform_owner(uuid, uuid, uuid, uuid, text, text, text)"
)
_TRANSITION = (
    "request_platform.transition_native_platform_owner(uuid, text, bigint, text, text, text, text)"
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")

    op.execute(
        """
        INSERT INTO request_engine.platform_owner_policies (policy_key, revision, grants)
        VALUES (
            'platform-owner-v2',
            2,
            '[
                {"capability_key": "platform.principal.provision", "delegable": true},
                {"capability_key": "platform.tenant_provisioner.provision", "delegable": true},
                {"capability_key": "platform.recovery_operator.provision", "delegable": false},
                {"capability_key": "organization.provision", "delegable": true},
                {"capability_key": "platform.identity.recover", "delegable": false},
                {"capability_key": "platform.identity.read", "delegable": false},
                {"capability_key": "platform.identity.provision", "delegable": false},
                {"capability_key": "platform.identity.recovery_approve", "delegable": false},
                {"capability_key": "platform.provisioner.read", "delegable": false},
                {"capability_key": "platform.provisioner.manage_lifecycle", "delegable": false},
                {"capability_key": "platform.owner.read", "delegable": false},
                {"capability_key": "platform.owner.provision", "delegable": false},
                {"capability_key": "platform.owner.manage_lifecycle", "delegable": false}
            ]'::jsonb
        );

        CREATE TABLE request_engine.platform_owner_provisioning_facts (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            principal_id uuid NOT NULL REFERENCES request_engine.principals(id),
            native_identity_id uuid NOT NULL REFERENCES request_engine.native_identities(id),
            actor_principal_id uuid NOT NULL REFERENCES request_engine.principals(id),
            policy_key text NOT NULL,
            provenance_reference text NOT NULL,
            idempotency_key_digest text NOT NULL,
            intent_digest text NOT NULL,
            correlation_id uuid,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            CONSTRAINT platform_owner_provisioning_policy_check
                CHECK (policy_key = 'platform-owner-v2'),
            CONSTRAINT platform_owner_provisioning_provenance_check
                CHECK (length(btrim(provenance_reference)) BETWEEN 1 AND 500),
            CONSTRAINT platform_owner_provisioning_key_check
                CHECK (idempotency_key_digest ~ '^[0-9a-f]{64}$'),
            CONSTRAINT platform_owner_provisioning_intent_check
                CHECK (intent_digest ~ '^[0-9a-f]{64}$'),
            CONSTRAINT platform_owner_provisioning_actor_key_uq
                UNIQUE (actor_principal_id, idempotency_key_digest)
        );
        ALTER TABLE request_engine.platform_owner_provisioning_facts
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON request_engine.platform_owner_provisioning_facts FROM PUBLIC;
        CREATE TRIGGER platform_owner_provisioning_facts_append_only
            BEFORE UPDATE OR DELETE ON request_engine.platform_owner_provisioning_facts
            FOR EACH ROW EXECUTE FUNCTION request_engine.reject_immutable_mutation();
        """
    )

    op.execute(
        """
        CREATE FUNCTION request_platform.grant_platform_owner_v2_capabilities_on_claim()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $$
        BEGIN
            IF OLD.state = 'unclaimed'
               AND NEW.state = 'claimed'
               AND NEW.initial_owner_principal_id IS NOT NULL
               AND EXISTS (
                   SELECT 1
                     FROM request_engine.principals AS principal
                    WHERE principal.id = NEW.initial_owner_principal_id
                      AND principal.principal_plane = 'platform'
                      AND principal.principal_kind = 'human'
                      AND principal.active
               )
            THEN
                INSERT INTO request_engine.principal_authority_grants (
                    principal_id, principal_plane, authority_plane, capability_key,
                    delegable, provenance_kind, provenance_reference
                )
                SELECT NEW.initial_owner_principal_id,
                       'platform',
                       'platform',
                       capability.capability_key,
                       false,
                       'trust_bootstrap',
                       'platform-owner-v2-claim:' || NEW.id::text
                  FROM (
                      VALUES ('platform.owner.read'),
                             ('platform.owner.provision'),
                             ('platform.owner.manage_lifecycle'),
                             ('platform.identity.provision')
                  ) AS capability(capability_key)
                 WHERE NOT EXISTS (
                     SELECT 1
                       FROM request_engine.principal_authority_grants AS existing
                      WHERE existing.principal_id = NEW.initial_owner_principal_id
                        AND existing.capability_key = capability.capability_key
                        AND existing.status = 'active'
                 );
            END IF;
            RETURN NEW;
        END
        $$;
        ALTER FUNCTION request_platform.grant_platform_owner_v2_capabilities_on_claim()
            OWNER TO request_platform_control_definer;
        REVOKE ALL ON FUNCTION
            request_platform.grant_platform_owner_v2_capabilities_on_claim() FROM PUBLIC;
        CREATE TRIGGER platform_instance_grant_owner_v2_capabilities
            AFTER UPDATE OF state ON request_engine.platform_instance
            FOR EACH ROW
            WHEN (OLD.state IS DISTINCT FROM NEW.state)
            EXECUTE FUNCTION request_platform.grant_platform_owner_v2_capabilities_on_claim();
        """
    )

    op.execute(
        f"""
        GRANT SELECT (id, principal_kind, active, authority_revision),
              INSERT (id, principal_plane, principal_kind, external_subject)
        ON request_engine.principals TO {_CONTROL_DEFINER};
        GRANT SELECT (id, principal_id, principal_plane, identity_authority_id,
                      subject_id, status, organization_id, revision),
              INSERT (id, principal_id, principal_plane, identity_authority_id,
                      subject_id, status),
              UPDATE (status, revision, revoked_at)
        ON request_engine.identity_bindings TO {_CONTROL_DEFINER};
        GRANT SELECT (principal_id, principal_plane, authority_plane, capability_key,
                      delegable, status, provenance_kind, provenance_reference,
                      revision),
              INSERT (principal_id, principal_plane, authority_plane, capability_key,
                      delegable, granted_by_principal_id, provenance_kind,
                      provenance_reference),
              UPDATE (status, revision, revoked_at, revoked_by_principal_id)
        ON request_engine.principal_authority_grants TO {_CONTROL_DEFINER};
        GRANT SELECT (id, kind, status)
        ON request_engine.identity_authorities TO {_CONTROL_DEFINER};
        GRANT SELECT (id, identity_authority_id, status)
        ON request_engine.native_identities TO {_CONTROL_DEFINER};
        GRANT SELECT (native_identity_id, kind, status)
        ON request_engine.native_credentials TO {_CONTROL_DEFINER};
        GRANT SELECT (native_identity_id, status, user_verified)
        ON request_engine.webauthn_credentials TO {_CONTROL_DEFINER};
        GRANT SELECT (id, native_identity_id, status)
        ON request_engine.recovery_code_sets TO {_CONTROL_DEFINER};
        GRANT SELECT (set_id, used_at)
        ON request_engine.recovery_codes TO {_CONTROL_DEFINER};
        GRANT SELECT (policy_key, revision, grants)
        ON request_engine.platform_owner_policies TO {_CONTROL_DEFINER};
        GRANT SELECT (id, principal_id, native_identity_id, actor_principal_id,
                      policy_key, provenance_reference, idempotency_key_digest,
                      intent_digest, correlation_id),
              INSERT (principal_id, native_identity_id, actor_principal_id,
                      policy_key, provenance_reference, idempotency_key_digest,
                      intent_digest, correlation_id)
        ON request_engine.platform_owner_provisioning_facts TO {_CONTROL_DEFINER};
        """
    )

    op.execute(
        r"""
        CREATE FUNCTION request_platform.native_identity_ready_for_platform_owner(
            p_identity_authority_id uuid,
            p_native_identity_id uuid
        ) RETURNS boolean
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $$
            SELECT EXISTS (
                SELECT 1
                  FROM request_engine.identity_authorities AS authority
                  JOIN request_engine.native_identities AS identity
                    ON identity.identity_authority_id = authority.id
                 WHERE authority.id = p_identity_authority_id
                   AND authority.kind = 'native'
                   AND authority.status = 'active'
                   AND identity.id = p_native_identity_id
                   AND identity.status = 'active'
                   AND EXISTS (
                       SELECT 1
                         FROM request_engine.native_credentials AS password
                        WHERE password.native_identity_id = identity.id
                          AND password.kind = 'password'
                          AND password.status = 'active'
                   )
                   AND EXISTS (
                       SELECT 1
                         FROM request_engine.webauthn_credentials AS credential
                        WHERE credential.native_identity_id = identity.id
                          AND credential.status = 'active'
                          AND credential.user_verified
                   )
                   AND EXISTS (
                       SELECT 1
                         FROM request_engine.recovery_code_sets AS code_set
                        WHERE code_set.native_identity_id = identity.id
                          AND code_set.status = 'active'
                          AND EXISTS (
                              SELECT 1
                                FROM request_engine.recovery_codes AS code
                               WHERE code.set_id = code_set.id
                                 AND code.used_at IS NULL
                          )
                   )
            )
        $$;
        ALTER FUNCTION request_platform.native_identity_ready_for_platform_owner(uuid, uuid)
            OWNER TO request_platform_control_definer;
        REVOKE ALL ON FUNCTION
            request_platform.native_identity_ready_for_platform_owner(uuid, uuid) FROM PUBLIC;

        CREATE FUNCTION request_platform.principal_is_effective_platform_owner(
            p_principal_id uuid
        ) RETURNS boolean
        LANGUAGE plpgsql
        STABLE
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $$
        DECLARE
            v_binding record;
            v_subject uuid;
        BEGIN
            PERFORM 1
              FROM request_engine.principals AS principal
             WHERE principal.id = p_principal_id
               AND principal.principal_plane = 'platform'
               AND principal.principal_kind = 'human'
               AND principal.active;
            IF NOT FOUND THEN
                RETURN false;
            END IF;
            IF NOT EXISTS (
                SELECT 1
                  FROM request_engine.principal_authority_grants AS grant_row
                 WHERE grant_row.principal_id = p_principal_id
                   AND grant_row.principal_plane = 'platform'
                   AND grant_row.authority_plane = 'platform'
                   AND grant_row.status = 'active'
                   AND grant_row.capability_key = 'platform.owner.manage_lifecycle'
            ) THEN
                RETURN false;
            END IF;
            FOR v_binding IN
                SELECT binding.identity_authority_id, binding.subject_id
                  FROM request_engine.identity_bindings AS binding
                 WHERE binding.principal_id = p_principal_id
                   AND binding.principal_plane = 'platform'
                   AND binding.organization_id IS NULL
                   AND binding.status = 'active'
                 ORDER BY binding.id
            LOOP
                BEGIN
                    v_subject := v_binding.subject_id::uuid;
                EXCEPTION WHEN invalid_text_representation THEN
                    CONTINUE;
                END;
                IF request_platform.native_identity_ready_for_platform_owner(
                    v_binding.identity_authority_id, v_subject
                ) THEN
                    RETURN true;
                END IF;
            END LOOP;
            RETURN false;
        END
        $$;
        ALTER FUNCTION request_platform.principal_is_effective_platform_owner(uuid)
            OWNER TO request_platform_control_definer;
        REVOKE ALL ON FUNCTION request_platform.principal_is_effective_platform_owner(uuid)
            FROM PUBLIC;

        CREATE FUNCTION request_platform.assert_other_platform_owner(
            p_excluded_principal_id uuid
        ) RETURNS void
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $$
        DECLARE
            v_candidate uuid;
        BEGIN
            PERFORM principal.id
              FROM request_engine.principals AS principal
             WHERE principal.principal_plane = 'platform'
             ORDER BY principal.id
             FOR UPDATE;

            SELECT principal.id
              INTO v_candidate
              FROM request_engine.principals AS principal
             WHERE principal.principal_plane = 'platform'
               AND principal.id <> p_excluded_principal_id
               AND request_platform.principal_is_effective_platform_owner(principal.id)
             ORDER BY principal.id
             LIMIT 1;
            IF v_candidate IS NULL THEN
                RAISE EXCEPTION 'Platform must retain an effective Platform Owner'
                    USING ERRCODE = '23514';
            END IF;
        END
        $$;
        ALTER FUNCTION request_platform.assert_other_platform_owner(uuid)
            OWNER TO request_platform_control_definer;
        REVOKE ALL ON FUNCTION request_platform.assert_other_platform_owner(uuid)
            FROM PUBLIC;
        """
    )

    op.execute(
        r"""
        CREATE FUNCTION request_platform.provision_native_platform_owner(
            p_principal_id uuid,
            p_binding_id uuid,
            p_identity_authority_id uuid,
            p_native_identity_id uuid,
            p_provenance_reference text,
            p_idempotency_key_digest text,
            p_intent_digest text
        ) RETURNS uuid
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $$
        DECLARE
            v_actor_id uuid;
            v_actor_revision bigint;
            v_actor_current_revision bigint;
            v_actor_kind text;
            v_actor_active boolean;
            v_correlation_id uuid;
            v_policy record;
            v_existing record;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();

            IF p_principal_id IS NULL OR p_binding_id IS NULL
               OR p_identity_authority_id IS NULL OR p_native_identity_id IS NULL
               OR p_provenance_reference IS NULL
               OR length(btrim(p_provenance_reference)) NOT BETWEEN 1 AND 500
               OR p_idempotency_key_digest !~ '^[0-9a-f]{64}$'
               OR p_intent_digest !~ '^[0-9a-f]{64}$'
            THEN
                RAISE EXCEPTION 'Platform Owner provisioning input is invalid'
                    USING ERRCODE = '22023';
            END IF;

            BEGIN
                v_actor_id := NULLIF(current_setting(
                    'request_engine.authenticated_principal_id', true
                ), '')::uuid;
                v_actor_revision := NULLIF(current_setting(
                    'request_engine.authority_revision', true
                ), '')::bigint;
                v_correlation_id := NULLIF(current_setting(
                    'request_engine.correlation_id', true
                ), '')::uuid;
            EXCEPTION WHEN invalid_text_representation THEN
                RAISE EXCEPTION 'Platform actor provenance is malformed'
                    USING ERRCODE = '28000';
            END;
            IF v_actor_id IS NULL OR v_actor_revision IS NULL THEN
                RAISE EXCEPTION 'Platform actor provenance is required'
                    USING ERRCODE = '28000';
            END IF;

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
                RAISE EXCEPTION 'Platform Owner provisioning requires an active HUMAN owner'
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
                   AND actor_grant.capability_key = 'platform.owner.provision'
            ) THEN
                RAISE EXCEPTION 'Current Platform Principal lacks owner provisioning authority'
                    USING ERRCODE = '42501';
            END IF;

            SELECT fact.principal_id, fact.native_identity_id, fact.intent_digest
              INTO v_existing
              FROM request_engine.platform_owner_provisioning_facts AS fact
             WHERE fact.actor_principal_id = v_actor_id
               AND fact.idempotency_key_digest = p_idempotency_key_digest;
            IF FOUND THEN
                IF v_existing.native_identity_id <> p_native_identity_id
                   OR v_existing.intent_digest <> p_intent_digest THEN
                    RAISE EXCEPTION
                        'Idempotency key was already used for another owner provisioning intent'
                        USING ERRCODE = '23505';
                END IF;
                RETURN v_existing.principal_id;
            END IF;

            IF EXISTS (
                SELECT 1
                  FROM request_engine.identity_bindings AS actor_binding
                 WHERE actor_binding.principal_id = v_actor_id
                   AND actor_binding.principal_plane = 'platform'
                   AND actor_binding.organization_id IS NULL
                   AND actor_binding.status = 'active'
                   AND actor_binding.identity_authority_id = p_identity_authority_id
                   AND actor_binding.subject_id = p_native_identity_id::text
            ) THEN
                RAISE EXCEPTION 'Self-elevation to Platform Owner is not allowed'
                    USING ERRCODE = '42501';
            END IF;

            IF NOT request_platform.native_identity_ready_for_platform_owner(
                p_identity_authority_id, p_native_identity_id
            ) THEN
                RAISE EXCEPTION
                    'Platform Owner requires active password, verified passkey and recovery codes'
                    USING ERRCODE = '23514';
            END IF;

            IF EXISTS (
                SELECT 1
                  FROM request_engine.identity_bindings AS binding
                 WHERE binding.identity_authority_id = p_identity_authority_id
                   AND binding.subject_id = p_native_identity_id::text
                   AND binding.principal_plane = 'platform'
            ) THEN
                RAISE EXCEPTION 'Native identity already has platform binding history'
                    USING ERRCODE = '23505';
            END IF;

            SELECT policy.* INTO v_policy
              FROM request_engine.platform_owner_policies AS policy
             WHERE policy.policy_key = 'platform-owner-v2';
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Platform Owner policy is missing'
                    USING ERRCODE = '55000';
            END IF;

            INSERT INTO request_engine.principals (
                id, principal_plane, principal_kind, external_subject
            ) VALUES (
                p_principal_id, 'platform', 'human',
                'native-platform-owner:' || p_native_identity_id::text
            );
            INSERT INTO request_engine.identity_bindings (
                id, principal_id, principal_plane, identity_authority_id, subject_id, status
            ) VALUES (
                p_binding_id, p_principal_id, 'platform',
                p_identity_authority_id, p_native_identity_id::text, 'active'
            );
            INSERT INTO request_engine.principal_authority_grants (
                principal_id, principal_plane, authority_plane, capability_key,
                delegable, granted_by_principal_id, provenance_kind, provenance_reference
            )
            SELECT p_principal_id, 'platform', 'platform',
                   grant_item ->> 'capability_key',
                   coalesce((grant_item ->> 'delegable')::boolean, false),
                   v_actor_id, 'platform_owner', btrim(p_provenance_reference)
              FROM jsonb_array_elements(v_policy.grants) AS grant_item;

            INSERT INTO request_engine.platform_owner_provisioning_facts (
                principal_id, native_identity_id, actor_principal_id, policy_key,
                provenance_reference, idempotency_key_digest, intent_digest,
                correlation_id
            ) VALUES (
                p_principal_id, p_native_identity_id, v_actor_id, v_policy.policy_key,
                btrim(p_provenance_reference), p_idempotency_key_digest,
                p_intent_digest, v_correlation_id
            );
            RETURN p_principal_id;
        END
        $$;
        """
    )

    op.execute(
        r"""
        CREATE FUNCTION request_platform.transition_native_platform_owner(
            p_principal_id uuid,
            p_action text,
            p_expected_revision bigint,
            p_reason_code text,
            p_external_case_reference text,
            p_idempotency_key_digest text,
            p_intent_digest text
        ) RETURNS TABLE (
            fact_id uuid,
            principal_id uuid,
            action text,
            authority_revision bigint,
            binding_id uuid,
            binding_status text
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $$
        DECLARE
            v_actor_id uuid;
            v_actor_revision bigint;
            v_actor_current_revision bigint;
            v_actor_kind text;
            v_actor_active boolean;
            v_actor_method text;
            v_correlation_id uuid;
            v_target_kind text;
            v_target_active boolean;
            v_revision_before bigint;
            v_revision_after bigint;
            v_binding_id uuid;
            v_binding_status text;
            v_binding_authority uuid;
            v_binding_subject text;
            v_subject uuid;
            v_replay record;
            v_fact_id uuid;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();

            IF p_principal_id IS NULL OR p_expected_revision IS NULL
               OR p_expected_revision < 1
               OR p_action NOT IN ('suspend', 'reactivate', 'revoke')
               OR p_reason_code IS NULL
               OR length(btrim(p_reason_code)) NOT BETWEEN 1 AND 80
               OR (p_external_case_reference IS NOT NULL
                   AND length(btrim(p_external_case_reference)) NOT BETWEEN 1 AND 200)
               OR p_idempotency_key_digest !~ '^[0-9a-f]{64}$'
               OR p_intent_digest !~ '^[0-9a-f]{64}$'
            THEN
                RAISE EXCEPTION 'Platform Owner lifecycle input is invalid'
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

            PERFORM principal.id
              FROM request_engine.principals AS principal
             WHERE principal.principal_plane = 'platform'
             ORDER BY principal.id
             FOR UPDATE;

            SELECT principal.principal_kind, principal.active, principal.authority_revision
              INTO v_actor_kind, v_actor_active, v_actor_current_revision
              FROM request_engine.principals AS principal
             WHERE principal.id = v_actor_id
               AND principal.principal_plane = 'platform';
            IF NOT FOUND OR NOT v_actor_active OR v_actor_kind <> 'human' THEN
                RAISE EXCEPTION 'Platform Owner lifecycle requires an active HUMAN owner'
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
                   AND actor_grant.status = 'active'
                   AND actor_grant.capability_key = 'platform.owner.manage_lifecycle'
            ) THEN
                RAISE EXCEPTION 'Current Platform Principal lacks owner lifecycle authority'
                    USING ERRCODE = '42501';
            END IF;

            SELECT fact.id, fact.principal_id, fact.action, fact.intent_digest,
                   fact.revision_after
              INTO v_replay
              FROM request_engine.platform_authority_lifecycle_facts AS fact
             WHERE fact.actor_principal_id = v_actor_id
               AND fact.capability_key = 'platform.owner.manage_lifecycle'
               AND fact.idempotency_key_digest = p_idempotency_key_digest;
            IF FOUND THEN
                IF v_replay.principal_id <> p_principal_id
                   OR v_replay.action <> p_action
                   OR v_replay.intent_digest <> p_intent_digest THEN
                    RAISE EXCEPTION
                        'Idempotency key was already used for another owner lifecycle intent'
                        USING ERRCODE = '23505';
                END IF;
                SELECT binding.id, binding.status
                  INTO v_binding_id, v_binding_status
                  FROM request_engine.identity_bindings AS binding
                 WHERE binding.principal_id = p_principal_id
                   AND binding.principal_plane = 'platform'
                   AND binding.organization_id IS NULL
                 ORDER BY (binding.status <> 'revoked') DESC, binding.id
                 LIMIT 1;
                RETURN QUERY SELECT v_replay.id, v_replay.principal_id, v_replay.action,
                                    v_replay.revision_after, v_binding_id, v_binding_status;
                RETURN;
            END IF;

            SELECT principal.principal_kind, principal.active, principal.authority_revision
              INTO v_target_kind, v_target_active, v_revision_before
              FROM request_engine.principals AS principal
             WHERE principal.id = p_principal_id
               AND principal.principal_plane = 'platform';
            IF NOT FOUND OR v_target_kind <> 'human' OR NOT v_target_active THEN
                RAISE EXCEPTION 'Target is not an active Platform Owner'
                    USING ERRCODE = '22023';
            END IF;
            IF NOT EXISTS (
                SELECT 1
                  FROM request_engine.principal_authority_grants AS grant_row
                 WHERE grant_row.principal_id = p_principal_id
                   AND grant_row.principal_plane = 'platform'
                   AND grant_row.authority_plane = 'platform'
                   AND grant_row.status = 'active'
                   AND grant_row.capability_key = 'platform.owner.manage_lifecycle'
            ) THEN
                RAISE EXCEPTION 'Target is not a Platform Owner'
                    USING ERRCODE = '22023';
            END IF;
            IF v_revision_before <> p_expected_revision THEN
                RAISE EXCEPTION 'Target authority revision is stale'
                    USING ERRCODE = '40001';
            END IF;

            SELECT binding.id, binding.status, binding.identity_authority_id, binding.subject_id
              INTO v_binding_id, v_binding_status, v_binding_authority, v_binding_subject
              FROM request_engine.identity_bindings AS binding
             WHERE binding.principal_id = p_principal_id
               AND binding.principal_plane = 'platform'
               AND binding.organization_id IS NULL
               AND binding.status <> 'revoked'
             ORDER BY binding.id
             LIMIT 1
             FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Platform Owner has no live identity binding'
                    USING ERRCODE = '55000';
            END IF;

            IF p_action = 'suspend' AND v_binding_status <> 'active' THEN
                RAISE EXCEPTION 'Only an active Platform Owner can be suspended'
                    USING ERRCODE = '55000';
            ELSIF p_action = 'reactivate' AND v_binding_status <> 'suspended' THEN
                RAISE EXCEPTION 'Only a suspended Platform Owner can be reactivated'
                    USING ERRCODE = '55000';
            ELSIF p_action = 'revoke'
               AND v_binding_status NOT IN ('active', 'suspended') THEN
                RAISE EXCEPTION 'Platform Owner is already terminally revoked'
                    USING ERRCODE = '55000';
            END IF;

            IF p_action IN ('suspend', 'revoke')
               AND request_platform.principal_is_effective_platform_owner(p_principal_id)
            THEN
                PERFORM request_platform.assert_other_platform_owner(p_principal_id);
            END IF;

            IF p_action = 'reactivate' THEN
                BEGIN
                    v_subject := v_binding_subject::uuid;
                EXCEPTION WHEN invalid_text_representation THEN
                    RAISE EXCEPTION 'Platform Owner native binding is not addressable'
                        USING ERRCODE = '23514';
                END;
                IF NOT request_platform.native_identity_ready_for_platform_owner(
                    v_binding_authority, v_subject
                ) THEN
                    RAISE EXCEPTION
                        'Reactivate requires password, verified passkey and recovery codes'
                        USING ERRCODE = '23514';
                END IF;
            END IF;

            IF p_action = 'suspend' THEN
                UPDATE request_engine.identity_bindings
                   SET status = 'suspended', revision = revision + 1
                 WHERE id = v_binding_id;
            ELSIF p_action = 'reactivate' THEN
                UPDATE request_engine.identity_bindings
                   SET status = 'active', revision = revision + 1
                 WHERE id = v_binding_id;
            ELSE
                UPDATE request_engine.identity_bindings
                   SET status = 'revoked', revision = revision + 1,
                       revoked_at = clock_timestamp()
                 WHERE id = v_binding_id;
                UPDATE request_engine.principal_authority_grants AS grant_row
                   SET status = 'revoked', revision = grant_row.revision + 1,
                       revoked_at = clock_timestamp(), revoked_by_principal_id = v_actor_id
                 WHERE grant_row.principal_id = p_principal_id
                   AND grant_row.principal_plane = 'platform'
                   AND grant_row.status = 'active';
            END IF;

            SELECT principal.authority_revision
              INTO v_revision_after
              FROM request_engine.principals AS principal
             WHERE principal.id = p_principal_id;

            v_fact_id := gen_random_uuid();
            INSERT INTO request_engine.platform_authority_lifecycle_facts (
                id, principal_id, action, actor_principal_id,
                actor_authentication_method, reason_code, external_case_reference,
                revision_before, revision_after, correlation_id, capability_key,
                idempotency_key_digest, intent_digest
            ) VALUES (
                v_fact_id, p_principal_id, p_action, v_actor_id, v_actor_method,
                btrim(p_reason_code), NULLIF(btrim(p_external_case_reference), ''),
                v_revision_before, v_revision_after, v_correlation_id,
                'platform.owner.manage_lifecycle', p_idempotency_key_digest, p_intent_digest
            );

            SELECT binding.status INTO v_binding_status
              FROM request_engine.identity_bindings AS binding
             WHERE binding.id = v_binding_id;

            RETURN QUERY SELECT v_fact_id, p_principal_id, p_action, v_revision_after,
                                v_binding_id, v_binding_status;
        END
        $$;
        """
    )

    for signature in (_PROVISION, _TRANSITION):
        op.execute(f"ALTER FUNCTION {signature} OWNER TO {_CONTROL_DEFINER}")
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO {_RUNTIME}")

    op.execute(
        """
        INSERT INTO request_engine.principal_authority_grants (
            principal_id, principal_plane, authority_plane, capability_key,
            delegable, provenance_kind, provenance_reference
        )
        SELECT controller.id, 'platform', 'platform', capability.capability_key,
               false, 'trust_bootstrap',
               'platform-owner-v2-upgrade:' || controller.id::text
          FROM request_engine.principals AS controller
          CROSS JOIN (
              VALUES ('platform.owner.read'),
                     ('platform.owner.provision'),
                     ('platform.owner.manage_lifecycle'),
                     ('platform.identity.provision')
          ) AS capability(capability_key)
         WHERE controller.principal_plane = 'platform'
           AND controller.principal_kind = 'human'
           AND controller.active
           AND EXISTS (
               SELECT 1
                 FROM request_engine.principal_authority_grants AS existing_root
                WHERE existing_root.principal_id = controller.id
                  AND existing_root.principal_plane = 'platform'
                  AND existing_root.authority_plane = 'platform'
                  AND existing_root.status = 'active'
                  AND existing_root.provenance_kind = 'trust_bootstrap'
                  AND existing_root.capability_key = 'platform.tenant_provisioner.provision'
           )
           AND NOT EXISTS (
               SELECT 1
                 FROM request_engine.principal_authority_grants AS existing
                WHERE existing.principal_id = controller.id
                  AND existing.capability_key = capability.capability_key
                  AND existing.status = 'active'
           );
        """
    )


def downgrade() -> None:
    raise RuntimeError("Platform Owner authority history is append-preserving; roll forward")
