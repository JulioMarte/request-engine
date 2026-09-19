"""Complete the platform provisioner lifecycle with revisioned private audit.

Adds the two ratified platform provisioner capabilities to the bootstrap trust
set, a platform controller continuity predicate, an append-only platform
authority lifecycle fact table, the bounded read projection and the single
revisioned/idempotent lifecycle command. Reactivation requires an authenticatable
native path and never restores revoked authority; revoke is terminal and never
deletes organizations previously provisioned.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0043_provisioner_lifecycle"
down_revision: str | Sequence[str] | None = "0042_controller_continuity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONTROL_DEFINER = "request_platform_control_definer"
_READ_DEFINER = "request_platform_definer"
_LIFECYCLE_FUNCTION = (
    "request_platform.transition_native_platform_provisioner(uuid, text, bigint, "
    "text, text, text, text)"
)
_READ_FUNCTION = "request_platform.read_platform_provisioners(uuid, uuid, integer)"
_ESTABLISH_ROOT_FUNCTION = (
    "request_platform.establish_root(uuid, bytea, uuid, uuid, text, uuid, text, uuid, uuid)"
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")

    # 1. Private append-only lifecycle audit facts. Platform-plane facts carry no
    # organization and grant no runtime table access; only the control definer
    # inserts through the command below.
    op.execute(
        """
        CREATE TABLE request_engine.platform_authority_lifecycle_facts (
            id uuid PRIMARY KEY,
            principal_id uuid NOT NULL REFERENCES request_engine.principals(id),
            action text NOT NULL,
            actor_principal_id uuid NOT NULL REFERENCES request_engine.principals(id),
            actor_authentication_method text NOT NULL,
            reason_code text NOT NULL,
            external_case_reference text,
            revision_before bigint NOT NULL,
            revision_after bigint NOT NULL,
            correlation_id uuid,
            capability_key text NOT NULL,
            idempotency_key_digest text NOT NULL,
            intent_digest text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            CONSTRAINT platform_authority_lifecycle_facts_action_check
                CHECK (action IN ('suspend', 'reactivate', 'revoke')),
            CONSTRAINT platform_authority_lifecycle_facts_method_check
                CHECK (length(btrim(actor_authentication_method)) > 0),
            CONSTRAINT platform_authority_lifecycle_facts_reason_check
                CHECK (length(btrim(reason_code)) BETWEEN 1 AND 80),
            CONSTRAINT platform_authority_lifecycle_facts_case_check CHECK (
                external_case_reference IS NULL
                OR length(btrim(external_case_reference)) BETWEEN 1 AND 200
            ),
            CONSTRAINT platform_authority_lifecycle_facts_revision_check
                CHECK (revision_before > 0 AND revision_after >= revision_before),
            CONSTRAINT platform_authority_lifecycle_facts_capability_check
                CHECK (length(btrim(capability_key)) > 0),
            CONSTRAINT platform_authority_lifecycle_facts_key_check
                CHECK (idempotency_key_digest ~ '^[0-9a-f]{64}$'),
            CONSTRAINT platform_authority_lifecycle_facts_intent_check
                CHECK (intent_digest ~ '^[0-9a-f]{64}$'),
            CONSTRAINT platform_authority_lifecycle_facts_actor_key_uq
                UNIQUE (actor_principal_id, capability_key, idempotency_key_digest)
        );
        ALTER TABLE request_engine.platform_authority_lifecycle_facts
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON request_engine.platform_authority_lifecycle_facts FROM PUBLIC;
        CREATE TRIGGER platform_authority_lifecycle_facts_append_only
            BEFORE DELETE OR UPDATE ON request_engine.platform_authority_lifecycle_facts
            FOR EACH ROW EXECUTE FUNCTION request_engine.reject_immutable_mutation();
        """
    )

    # 2. Platform controller continuity: an effective controller keeps an active
    # Principal, the current provisioner-administration grant and an active binding
    # to an active authority with a live credential path for native subjects. The
    # control definer owns it because platform bindings are invisible under tenant
    # RLS without BYPASSRLS.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION request_platform.principal_is_effective_platform_controller(
            p_principal_id uuid
        ) RETURNS boolean
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $$
        DECLARE
            v_binding record;
            v_authority_kind text;
            v_authority_status text;
        BEGIN
            PERFORM 1
              FROM request_engine.principals AS principal
             WHERE principal.id = p_principal_id
               AND principal.principal_plane = 'platform'
               AND principal.active;
            IF NOT FOUND THEN
                RETURN false;
            END IF;

            PERFORM 1
              FROM request_engine.principal_authority_grants AS grant_row
             WHERE grant_row.principal_id = p_principal_id
               AND grant_row.principal_plane = 'platform'
               AND grant_row.authority_plane = 'platform'
               AND grant_row.status = 'active'
               AND grant_row.capability_key = 'platform.tenant_provisioner.provision';
            IF NOT FOUND THEN
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
                SELECT authority.kind, authority.status
                  INTO v_authority_kind, v_authority_status
                  FROM request_engine.identity_authorities AS authority
                 WHERE authority.id = v_binding.identity_authority_id;
                IF NOT FOUND OR v_authority_status <> 'active' THEN
                    CONTINUE;
                END IF;

                IF v_authority_kind = 'native' THEN
                    PERFORM 1
                      FROM request_engine.native_identities AS identity
                      JOIN request_engine.native_credentials AS credential
                        ON credential.native_identity_id = identity.id
                       AND credential.kind = 'password'
                       AND credential.status = 'active'
                     WHERE identity.identity_authority_id = v_binding.identity_authority_id
                       AND identity.id::text = v_binding.subject_id
                       AND identity.status = 'active';
                    IF FOUND THEN
                        RETURN true;
                    END IF;
                ELSIF v_authority_kind = 'oidc' THEN
                    -- A configured external authenticator counts; upstream network
                    -- reachability and token revocation are not observable here.
                    RETURN true;
                END IF;
            END LOOP;

            RETURN false;
        END
        $$;
        ALTER FUNCTION request_platform.principal_is_effective_platform_controller(uuid)
            OWNER TO request_platform_control_definer;
        REVOKE ALL ON FUNCTION
            request_platform.principal_is_effective_platform_controller(uuid) FROM PUBLIC;

        CREATE OR REPLACE FUNCTION request_platform.assert_other_platform_controller(
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
        ALTER FUNCTION request_platform.assert_other_platform_controller(uuid)
            OWNER TO request_platform_control_definer;
        REVOKE ALL ON FUNCTION request_platform.assert_other_platform_controller(uuid)
            FROM PUBLIC;
        """
    )

    # 3. Bounded read projection for the private read login. The read definer keeps
    # only reviewed columns; the projection never returns credentials or subjects
    # outside the provisioner's own binding.
    op.execute(
        f"GRANT SELECT (provenance_kind, provenance_reference, granted_at) "
        f"ON request_engine.principal_authority_grants TO {_READ_DEFINER}"
    )
    op.execute(
        f"""
        CREATE FUNCTION request_platform.read_platform_provisioners(
            p_principal_id uuid,
            p_after uuid,
            p_limit integer
        ) RETURNS TABLE (
            principal_id uuid,
            principal_kind text,
            active boolean,
            authority_revision bigint,
            binding_id uuid,
            binding_status text,
            identity_authority_id uuid,
            binding_subject_id text,
            capabilities text[],
            provenance_reference text,
            granted_at timestamptz
        )
        LANGUAGE plpgsql
        STABLE
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $$
        BEGIN
            IF p_limit IS NULL OR p_limit < 1 OR p_limit > 100 THEN
                RAISE EXCEPTION 'Provisioner page limit must be between 1 and 100'
                    USING ERRCODE = '22023';
            END IF;
            RETURN QUERY
            WITH provisioner AS (
                SELECT principal.id,
                       principal.principal_kind,
                       principal.active,
                       principal.authority_revision
                  FROM request_engine.principals AS principal
                 WHERE principal.principal_plane = 'platform'
                   AND EXISTS (
                       SELECT 1
                         FROM request_engine.principal_authority_grants AS grant_row
                        WHERE grant_row.principal_id = principal.id
                          AND grant_row.principal_plane = 'platform'
                          AND grant_row.authority_plane = 'platform'
                          AND grant_row.provenance_kind = 'provisioning'
                   )
                   AND (p_principal_id IS NULL OR principal.id = p_principal_id)
                   AND (p_after IS NULL OR principal.id > p_after)
                 ORDER BY principal.id
                 LIMIT p_limit
            )
            SELECT provisioner.id,
                   provisioner.principal_kind,
                   provisioner.active,
                   provisioner.authority_revision,
                   binding.id,
                   binding.status,
                   binding.identity_authority_id,
                   binding.subject_id,
                   COALESCE(
                       (
                           SELECT array_agg(DISTINCT grant_row.capability_key
                                            ORDER BY grant_row.capability_key)
                             FROM request_engine.principal_authority_grants AS grant_row
                            WHERE grant_row.principal_id = provisioner.id
                              AND grant_row.principal_plane = 'platform'
                              AND grant_row.authority_plane = 'platform'
                              AND grant_row.status = 'active'
                       ),
                       ARRAY[]::text[]
                   ),
                   (
                       SELECT min(grant_row.provenance_reference)
                         FROM request_engine.principal_authority_grants AS grant_row
                        WHERE grant_row.principal_id = provisioner.id
                          AND grant_row.principal_plane = 'platform'
                          AND grant_row.provenance_kind = 'provisioning'
                   ),
                   (
                       SELECT min(grant_row.granted_at)
                         FROM request_engine.principal_authority_grants AS grant_row
                        WHERE grant_row.principal_id = provisioner.id
                          AND grant_row.principal_plane = 'platform'
                          AND grant_row.provenance_kind = 'provisioning'
                   )
              FROM provisioner
              LEFT JOIN LATERAL (
                  SELECT candidate.id,
                         candidate.status,
                         candidate.identity_authority_id,
                         candidate.subject_id
                    FROM request_engine.identity_bindings AS candidate
                   WHERE candidate.principal_id = provisioner.id
                     AND candidate.principal_plane = 'platform'
                     AND candidate.organization_id IS NULL
                   ORDER BY (candidate.status <> 'revoked') DESC, candidate.id
                   LIMIT 1
              ) AS binding ON true
             ORDER BY provisioner.id;
        END
        $$;
        ALTER FUNCTION {_READ_FUNCTION} OWNER TO {_READ_DEFINER};
        REVOKE ALL ON FUNCTION {_READ_FUNCTION} FROM PUBLIC;
        """
    )

    # 4. Reviewed column authority for the single lifecycle command and its
    # continuity predicate.
    op.execute(
        f"GRANT SELECT (id, identity_authority_id, status) "
        f"ON request_engine.native_identities TO {_CONTROL_DEFINER}"
    )
    op.execute(
        f"GRANT SELECT (native_identity_id, kind, status) "
        f"ON request_engine.native_credentials TO {_CONTROL_DEFINER}"
    )
    op.execute(
        f"GRANT SELECT (status, revision), UPDATE (status, revision, revoked_at) "
        f"ON request_engine.identity_bindings TO {_CONTROL_DEFINER}"
    )
    op.execute(
        f"GRANT SELECT (id, revision), "
        f"UPDATE (status, revision, revoked_at, revoked_by_principal_id) "
        f"ON request_engine.principal_authority_grants TO {_CONTROL_DEFINER}"
    )
    op.execute(
        f"GRANT SELECT (id, principal_id, action, intent_digest, revision_after, "
        f"actor_principal_id, capability_key, idempotency_key_digest), "
        f"INSERT (id, principal_id, action, actor_principal_id, "
        f"actor_authentication_method, reason_code, external_case_reference, "
        f"revision_before, revision_after, correlation_id, capability_key, "
        f"idempotency_key_digest, intent_digest) "
        f"ON request_engine.platform_authority_lifecycle_facts TO {_CONTROL_DEFINER}"
    )
    op.execute(
        f"""
        CREATE FUNCTION request_platform.transition_native_platform_provisioner(
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
            v_actor_method text;
            v_actor_kind text;
            v_actor_active boolean;
            v_actor_current_revision bigint;
            v_correlation_id uuid;
            v_target_kind text;
            v_target_active boolean;
            v_revision_before bigint;
            v_revision_after bigint;
            v_binding_id uuid;
            v_binding_status text;
            v_binding_authority uuid;
            v_binding_subject text;
            v_subject_uuid uuid;
            v_authority_kind text;
            v_replay record;
            v_fact_id uuid;
        BEGIN
            IF p_principal_id IS NULL OR p_expected_revision IS NULL
               OR p_expected_revision < 1 THEN
                RAISE EXCEPTION 'Target provisioner and expected revision are required'
                    USING ERRCODE = '22023';
            END IF;
            IF p_action IS NULL OR p_action NOT IN ('suspend', 'reactivate', 'revoke') THEN
                RAISE EXCEPTION 'Unknown platform provisioner lifecycle action'
                    USING ERRCODE = '22023';
            END IF;
            IF p_reason_code IS NULL
               OR length(btrim(p_reason_code)) NOT BETWEEN 1 AND 80
               OR (p_external_case_reference IS NOT NULL
                   AND length(btrim(p_external_case_reference)) NOT BETWEEN 1 AND 200)
               OR p_idempotency_key_digest !~ '^[0-9a-f]{{64}}$'
               OR p_intent_digest !~ '^[0-9a-f]{{64}}$' THEN
                RAISE EXCEPTION 'Lifecycle reason, case reference or digests are invalid'
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

            -- Platform-plane serialization root: every lifecycle command locks the
            -- platform Principal set in id order before bindings, grants or facts.
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
                RAISE EXCEPTION 'Current Platform Principal cannot manage provisioners'
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
                   AND actor_grant.capability_key = 'platform.provisioner.manage_lifecycle'
            ) THEN
                RAISE EXCEPTION 'Current Platform Principal lacks provisioner lifecycle authority'
                    USING ERRCODE = '42501';
            END IF;

            -- Replay is evaluated only after revalidating current actor authority.
            SELECT fact.id, fact.principal_id, fact.action, fact.intent_digest,
                   fact.revision_after
              INTO v_replay
              FROM request_engine.platform_authority_lifecycle_facts AS fact
             WHERE fact.actor_principal_id = v_actor_id
               AND fact.capability_key = 'platform.provisioner.manage_lifecycle'
               AND fact.idempotency_key_digest = p_idempotency_key_digest;
            IF FOUND THEN
                IF v_replay.principal_id <> p_principal_id
                   OR v_replay.action <> p_action
                   OR v_replay.intent_digest <> p_intent_digest THEN
                    RAISE EXCEPTION
                        'Idempotency key was already used for another lifecycle intent'
                        USING ERRCODE = '23505';
                END IF;
                SELECT candidate.id, candidate.status
                  INTO v_binding_id, v_binding_status
                  FROM request_engine.identity_bindings AS candidate
                 WHERE candidate.principal_id = p_principal_id
                   AND candidate.principal_plane = 'platform'
                   AND candidate.organization_id IS NULL
                 ORDER BY (candidate.status <> 'revoked') DESC, candidate.id
                 LIMIT 1;
                RETURN QUERY SELECT v_replay.id, v_replay.principal_id, v_replay.action,
                                    v_replay.revision_after, v_binding_id,
                                    v_binding_status;
                RETURN;
            END IF;

            SELECT principal.principal_kind, principal.active,
                   principal.authority_revision
              INTO v_target_kind, v_target_active, v_revision_before
              FROM request_engine.principals AS principal
             WHERE principal.id = p_principal_id
               AND principal.principal_plane = 'platform';
            IF NOT FOUND OR v_target_kind <> 'human' OR NOT v_target_active THEN
                RAISE EXCEPTION 'Target is not an active platform provisioner'
                    USING ERRCODE = '22023';
            END IF;
            IF NOT EXISTS (
                SELECT 1
                  FROM request_engine.principal_authority_grants AS grant_row
                 WHERE grant_row.principal_id = p_principal_id
                   AND grant_row.principal_plane = 'platform'
                   AND grant_row.authority_plane = 'platform'
                   AND grant_row.provenance_kind = 'provisioning'
            ) THEN
                RAISE EXCEPTION 'Target is not a platform provisioner'
                    USING ERRCODE = '22023';
            END IF;
            IF v_revision_before <> p_expected_revision THEN
                RAISE EXCEPTION 'Target authority revision is stale'
                    USING ERRCODE = '40001';
            END IF;

            SELECT binding.id, binding.status, binding.identity_authority_id,
                   binding.subject_id
              INTO v_binding_id, v_binding_status, v_binding_authority,
                   v_binding_subject
              FROM request_engine.identity_bindings AS binding
             WHERE binding.principal_id = p_principal_id
               AND binding.principal_plane = 'platform'
               AND binding.organization_id IS NULL
               AND binding.status <> 'revoked'
             ORDER BY binding.id
             LIMIT 1
             FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Platform provisioner has no live identity binding'
                    USING ERRCODE = '55000';
            END IF;

            IF p_action = 'suspend' AND v_binding_status <> 'active' THEN
                RAISE EXCEPTION 'Only an active provisioner can be suspended'
                    USING ERRCODE = '55000';
            ELSIF p_action = 'reactivate' AND v_binding_status <> 'suspended' THEN
                RAISE EXCEPTION 'Only a suspended provisioner can be reactivated'
                    USING ERRCODE = '55000';
            ELSIF p_action = 'revoke'
               AND v_binding_status NOT IN ('active', 'suspended') THEN
                RAISE EXCEPTION 'Provisioner is already terminally revoked'
                    USING ERRCODE = '55000';
            END IF;

            IF p_action IN ('suspend', 'revoke')
               AND request_platform.principal_is_effective_platform_controller(
                       p_principal_id) THEN
                PERFORM request_platform.assert_other_platform_controller(p_principal_id);
            END IF;

            IF p_action = 'reactivate' THEN
                SELECT authority.kind
                  INTO v_authority_kind
                  FROM request_engine.identity_authorities AS authority
                 WHERE authority.id = v_binding_authority;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'Provisioner identity authority is unavailable'
                        USING ERRCODE = '23514';
                END IF;
                IF v_authority_kind = 'native' THEN
                    BEGIN
                        v_subject_uuid := v_binding_subject::uuid;
                    EXCEPTION WHEN invalid_text_representation THEN
                        RAISE EXCEPTION
                            'Provisioner native binding subject is not addressable'
                            USING ERRCODE = '23514';
                    END;
                    IF NOT request_auth.lock_credentialed_native_identity(
                        v_binding_authority, v_subject_uuid
                    ) THEN
                        RAISE EXCEPTION
                            'Reactivate requires an active credentialed Native identity'
                            USING ERRCODE = '23514';
                    END IF;
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
                       revoked_at = clock_timestamp(),
                       revoked_by_principal_id = v_actor_id
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
                v_fact_id, p_principal_id, p_action, v_actor_id,
                v_actor_method, btrim(p_reason_code),
                NULLIF(btrim(p_external_case_reference), ''),
                v_revision_before, v_revision_after, v_correlation_id,
                'platform.provisioner.manage_lifecycle',
                p_idempotency_key_digest, p_intent_digest
            );

            SELECT binding.status
              INTO v_binding_status
              FROM request_engine.identity_bindings AS binding
             WHERE binding.id = v_binding_id;

            RETURN QUERY SELECT v_fact_id, p_principal_id, p_action, v_revision_after,
                                v_binding_id, v_binding_status;
        END
        $$;
        ALTER FUNCTION {_LIFECYCLE_FUNCTION} OWNER TO {_CONTROL_DEFINER};
        REVOKE ALL ON FUNCTION {_LIFECYCLE_FUNCTION} FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION {_LIFECYCLE_FUNCTION} TO request_platform_control;
        """
    )

    # 5. The ratified platform provisioner capabilities join the bootstrap trust
    # set. Replace the root establishment function with the same signature and
    # owner, then extend every existing platform controller.
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION request_platform.establish_root(
            p_intent_id uuid,
            p_token_digest bytea,
            p_identity_authority_id uuid,
            p_native_identity_id uuid,
            p_login_handle text,
            p_credential_id uuid,
            p_password_verifier text,
            p_principal_id uuid,
            p_binding_id uuid
        ) RETURNS uuid
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $$
        DECLARE
            v_provenance text;
            v_authority_kind text;
            v_authority_status text;
        BEGIN
            -- Different intents must not race to create two initial Platform roots.
            PERFORM pg_catalog.pg_advisory_xact_lock(1380274257, 1902476356);

            SELECT provenance_reference
              INTO v_provenance
              FROM request_engine.platform_bootstrap_intents
             WHERE id = p_intent_id
               AND token_digest = p_token_digest
               AND permitted_action = 'platform.root.establish'
               AND status = 'pending'
               AND expires_at > clock_timestamp()
             FOR UPDATE;
            IF NOT FOUND THEN
                RETURN NULL;
            END IF;

            PERFORM 1 FROM request_engine.principals
             WHERE principal_plane = 'platform'
             LIMIT 1;
            IF FOUND THEN
                RAISE EXCEPTION 'Platform root already exists' USING ERRCODE = '55000';
            END IF;

            SELECT kind, status
              INTO v_authority_kind, v_authority_status
              FROM request_engine.identity_authorities
             WHERE id = p_identity_authority_id;
            IF NOT FOUND OR v_authority_kind <> 'native'
               OR v_authority_status <> 'active' THEN
                RAISE EXCEPTION 'Platform root requires an active Native identity authority'
                    USING ERRCODE = '23514';
            END IF;

            INSERT INTO request_engine.native_identities (
                id, identity_authority_id, login_handle
            ) VALUES (p_native_identity_id, p_identity_authority_id, p_login_handle);
            INSERT INTO request_engine.native_credentials (
                id, native_identity_id, verifier
            ) VALUES (p_credential_id, p_native_identity_id, p_password_verifier);
            INSERT INTO request_engine.principals (
                id, principal_plane, principal_kind, external_subject
            ) VALUES (
                p_principal_id,
                'platform',
                'human',
                'native-bootstrap:' || p_native_identity_id::text
            );
            INSERT INTO request_engine.identity_bindings (
                id, principal_id, principal_plane, identity_authority_id,
                subject_id, status
            ) VALUES (
                p_binding_id,
                p_principal_id,
                'platform',
                p_identity_authority_id,
                p_native_identity_id::text,
                'active'
            );

            INSERT INTO request_engine.principal_authority_grants (
                principal_id, principal_plane, authority_plane, capability_key,
                delegable, provenance_kind, provenance_reference
            )
            SELECT p_principal_id,
                   'platform',
                   'platform',
                   capability_key,
                   delegable,
                   'trust_bootstrap',
                   'platform-bootstrap:' || p_intent_id::text || ':' || v_provenance
              FROM (VALUES
                  ('platform.principal.provision', true),
                  ('platform.tenant_provisioner.provision', true),
                  ('organization.provision', true),
                  ('platform.identity.recover', false),
                  ('platform.provisioner.read', false),
                  ('platform.provisioner.manage_lifecycle', false)
              ) AS initial_grant(capability_key, delegable);

            UPDATE request_engine.platform_bootstrap_intents
               SET status = 'consumed',
                   revision = revision + 1,
                   consumed_at = clock_timestamp()
             WHERE id = p_intent_id;
            RETURN p_principal_id;
        END
        $$;
        ALTER FUNCTION {_ESTABLISH_ROOT_FUNCTION} OWNER TO request_bootstrap_definer;
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
               capability.capability_key,
               false,
               'trust_bootstrap',
               'platform-controller-policy-v1:' || controller.id::text
          FROM request_engine.principals AS controller
          JOIN request_engine.principal_authority_grants AS control_grant
            ON control_grant.principal_id = controller.id
           AND control_grant.principal_plane = 'platform'
           AND control_grant.authority_plane = 'platform'
           AND control_grant.capability_key = 'platform.tenant_provisioner.provision'
           AND control_grant.status = 'active'
          CROSS JOIN (
              VALUES ('platform.provisioner.read'),
                     ('platform.provisioner.manage_lifecycle')
          ) AS capability(capability_key)
         WHERE controller.principal_plane = 'platform'
           AND controller.active;
        """
    )


def downgrade() -> None:
    raise RuntimeError("Do not remove the platform provisioner lifecycle; roll forward")
