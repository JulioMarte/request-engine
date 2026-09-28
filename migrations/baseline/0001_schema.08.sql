                p_native_identity_id, p_setup_session_id, btrim(p_login_handle), p_verifier
            );
            RETURN true;
        END
        $_$;


ALTER FUNCTION request_platform.set_setup_pending_identity(p_native_identity_id uuid, p_setup_session_id uuid, p_login_handle text, p_verifier text) OWNER TO request_platform_control_definer;

--
-- Name: stage_platform_configuration(text, text, jsonb, uuid, text, text); Type: FUNCTION; Schema: request_platform; Owner: request_platform_control_definer
--

CREATE FUNCTION request_platform.stage_platform_configuration(p_configuration_kind text, p_provider_kind text, p_configuration jsonb, p_secret_binding_id uuid, p_idempotency_key_digest text, p_intent_digest text) RETURNS TABLE(configuration_revision_id uuid, revision bigint, state text)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $_$
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
                    'p7/idempotency/'
                    || v_actor_id::text
                    || '/platform.configuration.stage/'
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
                    'p7/configuration-kind/' || p_configuration_kind,
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
        $_$;


ALTER FUNCTION request_platform.stage_platform_configuration(p_configuration_kind text, p_provider_kind text, p_configuration jsonb, p_secret_binding_id uuid, p_idempotency_key_digest text, p_intent_digest text) OWNER TO request_platform_control_definer;

--
-- Name: transition_native_platform_owner(uuid, text, bigint, text, text, text, text); Type: FUNCTION; Schema: request_platform; Owner: request_platform_control_definer
--

CREATE FUNCTION request_platform.transition_native_platform_owner(p_principal_id uuid, p_action text, p_expected_revision bigint, p_reason_code text, p_external_case_reference text, p_idempotency_key_digest text, p_intent_digest text) RETURNS TABLE(fact_id uuid, principal_id uuid, action text, authority_revision bigint, binding_id uuid, binding_status text)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $_$
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
        $_$;


ALTER FUNCTION request_platform.transition_native_platform_owner(p_principal_id uuid, p_action text, p_expected_revision bigint, p_reason_code text, p_external_case_reference text, p_idempotency_key_digest text, p_intent_digest text) OWNER TO request_platform_control_definer;

--
-- Name: transition_native_platform_provisioner(uuid, text, bigint, text, text, text, text); Type: FUNCTION; Schema: request_platform; Owner: request_platform_control_definer
--

CREATE FUNCTION request_platform.transition_native_platform_provisioner(p_principal_id uuid, p_action text, p_expected_revision bigint, p_reason_code text, p_external_case_reference text, p_idempotency_key_digest text, p_intent_digest text) RETURNS TABLE(fact_id uuid, principal_id uuid, action text, authority_revision bigint, binding_id uuid, binding_status text)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $_$
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
            PERFORM request_engine.acquire_identity_topology_share();
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
               OR p_idempotency_key_digest !~ '^[0-9a-f]{64}$'
               OR p_intent_digest !~ '^[0-9a-f]{64}$' THEN
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
        $_$;


ALTER FUNCTION request_platform.transition_native_platform_provisioner(p_principal_id uuid, p_action text, p_expected_revision bigint, p_reason_code text, p_external_case_reference text, p_idempotency_key_digest text, p_intent_digest text) OWNER TO request_platform_control_definer;

--
-- Name: validate_platform_configuration(text, bigint, text, text); Type: FUNCTION; Schema: request_platform; Owner: request_platform_control_definer
--

CREATE FUNCTION request_platform.validate_platform_configuration(p_configuration_kind text, p_revision bigint, p_idempotency_key_digest text, p_intent_digest text) RETURNS TABLE(configuration_revision_id uuid, revision bigint, state text)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $_$
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
               OR p_idempotency_key_digest !~ '^[0-9a-f]{64}$'
               OR p_intent_digest !~ '^[0-9a-f]{64}$'
            THEN
                RAISE EXCEPTION 'Platform configuration validation input is invalid'
                    USING ERRCODE = '22023';
            END IF;

            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended(
                    'p7/idempotency/'
                    || v_actor_id::text
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
        $_$;


ALTER FUNCTION request_platform.validate_platform_configuration(p_configuration_kind text, p_revision bigint, p_idempotency_key_digest text, p_intent_digest text) OWNER TO request_platform_control_definer;

--
-- Name: validate_platform_configuration_provider(text, bigint, bigint, integer, text, text); Type: FUNCTION; Schema: request_platform; Owner: request_platform_control_definer
--

CREATE FUNCTION request_platform.validate_platform_configuration_provider(p_configuration_kind text, p_revision bigint, p_expected_binding_revision bigint, p_expected_backend_version integer, p_idempotency_key_digest text, p_intent_digest text) RETURNS TABLE(configuration_revision_id uuid, revision bigint, state text)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $_$
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
        $_$;


ALTER FUNCTION request_platform.validate_platform_configuration_provider(p_configuration_kind text, p_revision bigint, p_expected_binding_revision bigint, p_expected_backend_version integer, p_idempotency_key_digest text, p_intent_digest text) OWNER TO request_platform_control_definer;

--
-- Name: integrations(uuid, uuid, integer); Type: FUNCTION; Schema: request_read; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_read.integrations(p_principal_id uuid DEFAULT NULL::uuid, p_after uuid DEFAULT NULL::uuid, p_limit integer DEFAULT 50) RETURNS TABLE(principal_id uuid, authority_revision bigint, status text, binding_id uuid, workload_identity_id uuid, identity_authority_id uuid, capabilities text[], credentials jsonb, provenance_complete boolean)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        BEGIN
            PERFORM request_engine.assert_staff_manager('integration.read');
            IF p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 100 THEN
                RAISE EXCEPTION 'Integration page size must be between 1 and 100'
                    USING ERRCODE = '22023';
            END IF;
            RETURN QUERY
                SELECT pr.id, pr.authority_revision, COALESCE(b.status, 'revoked'),
                       b.id, wi.id, b.identity_authority_id,
                       ARRAY(SELECT g.capability_key
                           FROM request_engine.principal_authority_grants g
                           WHERE g.organization_id = pr.organization_id AND g.principal_id = pr.id
                             AND g.status = 'active' ORDER BY g.capability_key),
                       COALESCE((SELECT jsonb_agg(jsonb_build_object(
                           'credential_id', c.id, 'status', c.status,
                           'expires_at', c.expires_at, 'created_at', c.created_at
                       ) ORDER BY c.created_at, c.id)
                           FROM request_engine.workload_credentials c
                           WHERE c.workload_identity_id = wi.id
                             AND c.status = 'active'), '[]'::jsonb),
                       EXISTS (SELECT 1 FROM request_engine.integration_governance_facts f
                           WHERE f.organization_id = pr.organization_id
                             AND f.integration_principal_id = pr.id AND f.operation = 'provision')
                  FROM request_engine.principals pr
                  LEFT JOIN LATERAL (
                      SELECT ib.* FROM request_engine.identity_bindings ib
                       WHERE ib.organization_id = pr.organization_id AND ib.principal_id = pr.id
                       ORDER BY (ib.status <> 'revoked') DESC, ib.id LIMIT 1
                  ) b ON true
                  LEFT JOIN request_engine.workload_identities wi
                    ON wi.id::text = b.subject_id
                   AND wi.identity_authority_id = b.identity_authority_id
                 WHERE pr.organization_id = request_engine.current_organization_id()
                   AND pr.principal_kind = 'integration' AND pr.principal_plane = 'tenant'
                   AND (p_principal_id IS NULL OR pr.id = p_principal_id)
                   AND (p_after IS NULL OR pr.id > p_after)
                 ORDER BY pr.id LIMIT p_limit;
        END $$;


ALTER FUNCTION request_read.integrations(p_principal_id uuid, p_after uuid, p_limit integer) OWNER TO request_engine_schema_owner;

--
-- Name: recovery_source_revision(uuid, uuid); Type: FUNCTION; Schema: request_read; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_read.recovery_source_revision(p_organization_id uuid, p_service_queue_id uuid) RETURNS bigint
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
    SELECT revision
    FROM request_engine.recovery_source_revisions
    WHERE organization_id = p_organization_id
      AND service_queue_id = p_service_queue_id
$$;


ALTER FUNCTION request_read.recovery_source_revision(p_organization_id uuid, p_service_queue_id uuid) OWNER TO request_engine_schema_owner;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: outbox_messages; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.outbox_messages (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    event_type text NOT NULL,
    schema_version integer DEFAULT 1 NOT NULL,
    aggregate_kind text,
    aggregate_id uuid,
    payload jsonb NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    claim_token uuid,
    lease_until timestamp with time zone,
    attempt_count integer DEFAULT 0 NOT NULL,
    max_attempts integer DEFAULT 12 NOT NULL,
    next_attempt_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    last_error_class text,
    occurred_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    delivered_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    replay_count integer DEFAULT 0 NOT NULL,
    last_replayed_at timestamp with time zone,
    correlation_data jsonb DEFAULT '{}'::jsonb NOT NULL,
    CONSTRAINT outbox_messages_attempt_count_check CHECK ((attempt_count >= 0)),
    CONSTRAINT outbox_messages_check CHECK (((status = 'leased'::text) = ((claim_token IS NOT NULL) AND (lease_until IS NOT NULL)))),
    CONSTRAINT outbox_messages_check1 CHECK (((status <> 'delivered'::text) OR (delivered_at IS NOT NULL))),
    CONSTRAINT outbox_messages_correlation_data_object_ck CHECK ((jsonb_typeof(correlation_data) = 'object'::text)),
    CONSTRAINT outbox_messages_event_type_check CHECK ((event_type <> ''::text)),
    CONSTRAINT outbox_messages_max_attempts_check CHECK ((max_attempts > 0)),
    CONSTRAINT outbox_messages_payload_check CHECK ((jsonb_typeof(payload) = 'object'::text)),
    CONSTRAINT outbox_messages_replay_count_check CHECK ((replay_count >= 0)),
    CONSTRAINT outbox_messages_schema_version_check CHECK ((schema_version > 0)),
    CONSTRAINT outbox_messages_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'leased'::text, 'delivered'::text, 'dead'::text])))
);


ALTER TABLE request_engine.outbox_messages OWNER TO request_engine_schema_owner;

--
-- Name: provider_events; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.provider_events (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    provider_key text NOT NULL,
    connection_key text NOT NULL,
    provider_event_id text NOT NULL,
    payload_hash text NOT NULL,
    payload jsonb NOT NULL,
    status text DEFAULT 'received'::text NOT NULL,
    received_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    processed_at timestamp with time zone,
    error_class text,
    claim_token uuid,
    lease_until timestamp with time zone,
    attempt_count integer DEFAULT 0 NOT NULL,
    max_attempts integer DEFAULT 8 NOT NULL,
    next_attempt_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    last_error_class text,
    replay_count integer DEFAULT 0 NOT NULL,
    last_replayed_at timestamp with time zone,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT provider_events_attempt_count_check CHECK ((attempt_count >= 0)),
    CONSTRAINT provider_events_connection_key_check CHECK ((connection_key <> ''::text)),
    CONSTRAINT provider_events_lease_shape_check CHECK (((status = 'leased'::text) = ((claim_token IS NOT NULL) AND (lease_until IS NOT NULL)))),
    CONSTRAINT provider_events_max_attempts_check CHECK ((max_attempts > 0)),
    CONSTRAINT provider_events_payload_hash_check CHECK ((payload_hash <> ''::text)),
    CONSTRAINT provider_events_provider_event_id_check CHECK ((provider_event_id <> ''::text)),
    CONSTRAINT provider_events_provider_key_check CHECK ((provider_key <> ''::text)),
    CONSTRAINT provider_events_replay_count_check CHECK ((replay_count >= 0)),
    CONSTRAINT provider_events_status_v4_check CHECK ((status = ANY (ARRAY['received'::text, 'leased'::text, 'processed'::text, 'rejected'::text, 'dead'::text]))),
    CONSTRAINT provider_events_terminal_timestamp_check CHECK ((((status = ANY (ARRAY['processed'::text, 'rejected'::text])) AND (processed_at IS NOT NULL)) OR ((status <> ALL (ARRAY['processed'::text, 'rejected'::text])) AND (processed_at IS NULL))))
);


ALTER TABLE request_engine.provider_events OWNER TO request_engine_schema_owner;

--
-- Name: scheduled_actions; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.scheduled_actions (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    owner_module text NOT NULL,
    action_type text NOT NULL,
    action_version integer DEFAULT 1 NOT NULL,
    subject_kind text,
    subject_id uuid,
    payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    dedupe_key text NOT NULL,
    execute_at timestamp with time zone NOT NULL,
    next_attempt_at timestamp with time zone NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    claim_token uuid,
    lease_until timestamp with time zone,
    attempt_count integer DEFAULT 0 NOT NULL,
    max_attempts integer DEFAULT 8 NOT NULL,
    last_error_class text,
    completed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    replay_count integer DEFAULT 0 NOT NULL,
    last_replayed_at timestamp with time zone,
    correlation_data jsonb DEFAULT '{}'::jsonb NOT NULL,
    CONSTRAINT scheduled_actions_action_type_check CHECK ((action_type <> ''::text)),
    CONSTRAINT scheduled_actions_action_version_check CHECK ((action_version > 0)),
    CONSTRAINT scheduled_actions_attempt_count_check CHECK ((attempt_count >= 0)),
    CONSTRAINT scheduled_actions_check CHECK (((status = 'leased'::text) = ((claim_token IS NOT NULL) AND (lease_until IS NOT NULL)))),
    CONSTRAINT scheduled_actions_check1 CHECK (((status <> 'completed'::text) OR (completed_at IS NOT NULL))),
    CONSTRAINT scheduled_actions_correlation_data_object_ck CHECK ((jsonb_typeof(correlation_data) = 'object'::text)),
    CONSTRAINT scheduled_actions_dedupe_key_check CHECK ((dedupe_key <> ''::text)),
    CONSTRAINT scheduled_actions_max_attempts_check CHECK ((max_attempts > 0)),
    CONSTRAINT scheduled_actions_owner_module_check CHECK ((owner_module <> ''::text)),
    CONSTRAINT scheduled_actions_payload_check CHECK ((jsonb_typeof(payload) = 'object'::text)),
    CONSTRAINT scheduled_actions_replay_count_check CHECK ((replay_count >= 0)),
    CONSTRAINT scheduled_actions_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'leased'::text, 'completed'::text, 'cancelled'::text, 'dead'::text])))
);


ALTER TABLE request_engine.scheduled_actions OWNER TO request_engine_schema_owner;

--
-- Name: worker_dead_letters_v1; Type: VIEW; Schema: request_admin; Owner: request_engine_schema_owner
--

CREATE VIEW request_admin.worker_dead_letters_v1 AS
 SELECT scheduled_actions.organization_id,
    'scheduled_action'::text AS work_kind,
    scheduled_actions.id AS work_id,
    scheduled_actions.attempt_count,
    scheduled_actions.max_attempts,
    scheduled_actions.replay_count,
    scheduled_actions.last_error_class,
    scheduled_actions.updated_at
   FROM request_engine.scheduled_actions
  WHERE (scheduled_actions.status = 'dead'::text)
UNION ALL
 SELECT outbox_messages.organization_id,
    'outbox_message'::text AS work_kind,
    outbox_messages.id AS work_id,
    outbox_messages.attempt_count,
    outbox_messages.max_attempts,
    outbox_messages.replay_count,
    outbox_messages.last_error_class,
    outbox_messages.updated_at
   FROM request_engine.outbox_messages
  WHERE (outbox_messages.status = 'dead'::text)
UNION ALL
 SELECT provider_events.organization_id,
    'provider_event'::text AS work_kind,
    provider_events.id AS work_id,
    provider_events.attempt_count,
    provider_events.max_attempts,
    provider_events.replay_count,
    provider_events.last_error_class,
    provider_events.updated_at
   FROM request_engine.provider_events
  WHERE (provider_events.status = ANY (ARRAY['dead'::text, 'rejected'::text]));


ALTER VIEW request_admin.worker_dead_letters_v1 OWNER TO request_engine_schema_owner;

--
-- Name: agent_budget_windows; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.agent_budget_windows (
    organization_id uuid NOT NULL,
    agent_principal_id uuid NOT NULL,
    window_started_at timestamp with time zone NOT NULL,
    mutation_count integer DEFAULT 0 NOT NULL,
    CONSTRAINT agent_budget_windows_count_check CHECK ((mutation_count >= 0))
);

ALTER TABLE ONLY request_engine.agent_budget_windows FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.agent_budget_windows OWNER TO request_engine_schema_owner;

--
-- Name: agent_policies; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.agent_policies (
    organization_id uuid NOT NULL,
    agent_principal_id uuid NOT NULL,
    allowed_capabilities text[] DEFAULT '{}'::text[] NOT NULL,
    denied_capabilities text[] DEFAULT '{}'::text[] NOT NULL,
    risk_ceiling text NOT NULL,
    max_mutations_per_minute integer NOT NULL,
    policy_revision bigint DEFAULT 1 NOT NULL,
    provenance_reference text NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT agent_policies_budget_check CHECK ((max_mutations_per_minute > 0)),
    CONSTRAINT agent_policies_provenance_check CHECK (((length(btrim(provenance_reference)) >= 1) AND (length(btrim(provenance_reference)) <= 500))),
    CONSTRAINT agent_policies_revision_check CHECK ((policy_revision > 0)),
    CONSTRAINT agent_policies_risk_ceiling_check CHECK ((risk_ceiling = ANY (ARRAY['read'::text, 'low_impact_write'::text, 'reversible_write'::text, 'external_commitment'::text, 'sensitive_data'::text, 'financial'::text, 'destructive'::text])))
);

ALTER TABLE ONLY request_engine.agent_policies FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.agent_policies OWNER TO request_engine_schema_owner;

--
-- Name: agent_profiles; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.agent_profiles (
    principal_id uuid NOT NULL,
    organization_id uuid NOT NULL,
    display_name text NOT NULL,
    purpose text NOT NULL,
    sponsor_principal_id uuid NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    operating_mode text DEFAULT 'autonomous'::text NOT NULL,
    workload_identity_id uuid NOT NULL,
    established_by_principal_id uuid NOT NULL,
    provenance_kind text DEFAULT 'agent_provisioning'::text NOT NULL,
    provenance_reference text NOT NULL,
    revision bigint DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    suspended_at timestamp with time zone,
    revoked_at timestamp with time zone,
    CONSTRAINT agent_profiles_display_name_check CHECK (((length(btrim(display_name)) >= 1) AND (length(btrim(display_name)) <= 200))),
    CONSTRAINT agent_profiles_operating_mode_check CHECK ((operating_mode = ANY (ARRAY['autonomous'::text, 'assisted'::text]))),
    CONSTRAINT agent_profiles_provenance_kind_check CHECK ((provenance_kind = 'agent_provisioning'::text)),
    CONSTRAINT agent_profiles_provenance_reference_check CHECK (((length(btrim(provenance_reference)) >= 1) AND (length(btrim(provenance_reference)) <= 500))),
    CONSTRAINT agent_profiles_purpose_check CHECK (((length(btrim(purpose)) >= 1) AND (length(btrim(purpose)) <= 2000))),
    CONSTRAINT agent_profiles_revision_check CHECK ((revision > 0)),
    CONSTRAINT agent_profiles_state_time_check CHECK ((((status = 'pending'::text) AND (suspended_at IS NULL) AND (revoked_at IS NULL)) OR ((status = 'active'::text) AND (revoked_at IS NULL)) OR ((status = 'suspended'::text) AND (suspended_at IS NOT NULL) AND (revoked_at IS NULL)) OR ((status = 'revoked'::text) AND (revoked_at IS NOT NULL)))),
    CONSTRAINT agent_profiles_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'active'::text, 'suspended'::text, 'revoked'::text])))
);

ALTER TABLE ONLY request_engine.agent_profiles FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.agent_profiles OWNER TO request_engine_schema_owner;

--
-- Name: attendance_responses; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.attendance_responses (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    reservation_id uuid NOT NULL,
    response text NOT NULL,
    actor_principal_id uuid,
    source_key text NOT NULL,
    responded_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT attendance_responses_response_check CHECK ((response = ANY (ARRAY['accepted'::text, 'declined'::text]))),
    CONSTRAINT attendance_responses_source_key_check CHECK ((source_key <> ''::text))
);


ALTER TABLE request_engine.attendance_responses OWNER TO request_engine_schema_owner;

--
-- Name: audit_records; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.audit_records (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    actor_principal_id uuid,
    command_name text NOT NULL,
    aggregate_kind text,
    aggregate_id uuid,
    represented_party_id uuid,
    representation_id uuid,
    policy_key text,
    idempotency_record_id uuid,
    correlation_data jsonb DEFAULT '{}'::jsonb NOT NULL,
    details jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT audit_records_command_name_check CHECK ((command_name <> ''::text)),
    CONSTRAINT audit_records_correlation_data_check CHECK ((jsonb_typeof(correlation_data) = 'object'::text)),
    CONSTRAINT audit_records_details_check CHECK ((jsonb_typeof(details) = 'object'::text))
);


ALTER TABLE request_engine.audit_records OWNER TO request_engine_schema_owner;

--
-- Name: booking_context_terms; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.booking_context_terms (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    resource_location_assignment_id uuid NOT NULL,
    offering_version_id uuid NOT NULL,
    effective_during tstzrange NOT NULL,
    amount numeric(20,6),
    currency text,
    planned_duration_minutes integer,
    bookable boolean DEFAULT true NOT NULL,
    active boolean DEFAULT true NOT NULL,
    revision bigint DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT booking_context_terms_amount_check CHECK (((amount IS NULL) OR (amount >= (0)::numeric))),
    CONSTRAINT booking_context_terms_check CHECK (((amount IS NULL) = (currency IS NULL))),
    CONSTRAINT booking_context_terms_check1 CHECK (((amount IS NOT NULL) OR (planned_duration_minutes IS NOT NULL) OR (NOT bookable))),
    CONSTRAINT booking_context_terms_currency_check CHECK (((currency IS NULL) OR (currency ~ '^[A-Z]{3}$'::text))),
    CONSTRAINT booking_context_terms_effective_during_check CHECK ((NOT isempty(effective_during))),
    CONSTRAINT booking_context_terms_effective_during_check1 CHECK ((lower(effective_during) IS NOT NULL)),
    CONSTRAINT booking_context_terms_effective_during_check2 CHECK ((lower_inc(effective_during) AND (NOT upper_inc(effective_during)))),
    CONSTRAINT booking_context_terms_planned_duration_minutes_check CHECK (((planned_duration_minutes IS NULL) OR (planned_duration_minutes > 0))),
    CONSTRAINT booking_context_terms_revision_check CHECK ((revision > 0))
);

ALTER TABLE ONLY request_engine.booking_context_terms FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.booking_context_terms OWNER TO request_engine_schema_owner;

--
-- Name: capacity_claims; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.capacity_claims (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    resource_id uuid NOT NULL,
    requirement_id uuid NOT NULL,
    hold_id uuid,
    reservation_id uuid,
    during tstzrange NOT NULL,
    quantity integer NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    released_at timestamp with time zone,
    replaced_by_claim_id uuid,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    resource_location_assignment_id uuid,
    CONSTRAINT capacity_claims_check CHECK (((hold_id IS NOT NULL) OR (reservation_id IS NOT NULL))),
    CONSTRAINT capacity_claims_check1 CHECK (((status = 'active'::text) = (released_at IS NULL))),
    CONSTRAINT capacity_claims_check2 CHECK (((status <> 'replaced'::text) OR (replaced_by_claim_id IS NOT NULL))),
    CONSTRAINT capacity_claims_during_check CHECK ((NOT isempty(during))),
    CONSTRAINT capacity_claims_during_check1 CHECK (((lower(during) IS NOT NULL) AND (upper(during) IS NOT NULL))),
    CONSTRAINT capacity_claims_during_check2 CHECK ((lower_inc(during) AND (NOT upper_inc(during)))),
    CONSTRAINT capacity_claims_quantity_check CHECK ((quantity > 0)),
    CONSTRAINT capacity_claims_status_check CHECK ((status = ANY (ARRAY['active'::text, 'released'::text, 'replaced'::text])))
);


ALTER TABLE request_engine.capacity_claims OWNER TO request_engine_schema_owner;

--
-- Name: capacity_holds; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.capacity_holds (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    offering_version_id uuid NOT NULL,
    subject_party_id uuid NOT NULL,
    location_id uuid,
    during tstzrange NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    revision bigint DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT capacity_holds_check CHECK ((expires_at > created_at)),
    CONSTRAINT capacity_holds_during_check CHECK ((NOT isempty(during))),
    CONSTRAINT capacity_holds_during_check1 CHECK (((lower(during) IS NOT NULL) AND (upper(during) IS NOT NULL))),
    CONSTRAINT capacity_holds_during_check2 CHECK ((lower_inc(during) AND (NOT upper_inc(during)))),
    CONSTRAINT capacity_holds_revision_check CHECK ((revision > 0)),
    CONSTRAINT capacity_holds_status_check CHECK ((status = ANY (ARRAY['active'::text, 'consumed'::text, 'released'::text, 'expired'::text])))
);


ALTER TABLE request_engine.capacity_holds OWNER TO request_engine_schema_owner;

--
-- Name: communication_deliveries; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.communication_deliveries (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    communication_task_id uuid NOT NULL,
    attempt_no integer NOT NULL,
    channel text NOT NULL,
    provider_key text NOT NULL,
    provider_idempotency_key text NOT NULL,
    provider_message_id text,
    status text NOT NULL,
    result_data jsonb DEFAULT '{}'::jsonb NOT NULL,
    started_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    completed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT communication_deliveries_attempt_no_check CHECK ((attempt_no > 0)),
    CONSTRAINT communication_deliveries_channel_check CHECK ((channel <> ''::text)),
    CONSTRAINT communication_deliveries_provider_idempotency_key_check CHECK ((provider_idempotency_key <> ''::text)),
    CONSTRAINT communication_deliveries_provider_key_check CHECK ((provider_key <> ''::text)),
    CONSTRAINT communication_deliveries_result_data_check CHECK ((jsonb_typeof(result_data) = 'object'::text)),
    CONSTRAINT communication_deliveries_status_check CHECK ((status = ANY (ARRAY['attempting'::text, 'accepted'::text, 'delivered'::text, 'failed'::text, 'ambiguous'::text])))
);


ALTER TABLE request_engine.communication_deliveries OWNER TO request_engine_schema_owner;

--
-- Name: communication_escalations; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.communication_escalations (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    parent_task_id uuid NOT NULL,
    child_task_id uuid NOT NULL,
    trigger text NOT NULL,
    from_channel text NOT NULL,
    to_channel text NOT NULL,
    ordinal integer NOT NULL,
    failure_class text,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT communication_escalations_ordinal_check CHECK ((ordinal >= 1)),
    CONSTRAINT communication_escalations_trigger_check CHECK ((trigger = ANY (ARRAY['delivery_deadline_missed'::text, 'definitive_failure'::text, 'recipient_unreachable'::text])))
);

ALTER TABLE ONLY request_engine.communication_escalations FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.communication_escalations OWNER TO request_engine_schema_owner;

--
-- Name: communication_tasks; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.communication_tasks (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    recipient_party_id uuid NOT NULL,
    contact_point_id uuid,
    purpose text NOT NULL,
    source_kind text,
    source_id uuid,
    channel_policy jsonb DEFAULT '{}'::jsonb NOT NULL,
    template_key text NOT NULL,
    template_version integer NOT NULL,
    render_context jsonb DEFAULT '{}'::jsonb NOT NULL,
    dedupe_key text,
    not_before timestamp with time zone,
    expires_at timestamp with time zone,
    status text DEFAULT 'pending'::text NOT NULL,
    revision bigint DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    parent_task_id uuid,
    lineage_id uuid,
    escalation_ordinal integer,
    CONSTRAINT communication_tasks_channel_policy_check CHECK ((jsonb_typeof(channel_policy) = 'object'::text)),
    CONSTRAINT communication_tasks_check CHECK (((expires_at IS NULL) OR (not_before IS NULL) OR (expires_at > not_before))),
    CONSTRAINT communication_tasks_escalation_ordinal_check CHECK (((escalation_ordinal IS NULL) OR (escalation_ordinal >= 1))),
    CONSTRAINT communication_tasks_lineage_shape_check CHECK ((((parent_task_id IS NULL) AND (lineage_id IS NULL) AND (escalation_ordinal IS NULL)) OR ((parent_task_id IS NOT NULL) AND (lineage_id IS NOT NULL) AND (escalation_ordinal IS NOT NULL)))),
    CONSTRAINT communication_tasks_purpose_check CHECK ((purpose <> ''::text)),
    CONSTRAINT communication_tasks_render_context_check CHECK ((jsonb_typeof(render_context) = 'object'::text)),
    CONSTRAINT communication_tasks_revision_check CHECK ((revision > 0)),
    CONSTRAINT communication_tasks_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'delivering'::text, 'completed'::text, 'cancelled'::text, 'failed'::text]))),
    CONSTRAINT communication_tasks_template_key_check CHECK ((template_key <> ''::text)),
    CONSTRAINT communication_tasks_template_version_check CHECK ((template_version > 0))
);


ALTER TABLE request_engine.communication_tasks OWNER TO request_engine_schema_owner;

--
-- Name: delegations; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.delegations (
    id uuid NOT NULL,
    organization_id uuid NOT NULL,
    delegator_principal_id uuid NOT NULL,
    delegate_principal_id uuid NOT NULL,
    purpose text NOT NULL,
    allowed_capabilities text[] NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    revision bigint DEFAULT 1 NOT NULL,
    not_before timestamp with time zone NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    provenance_reference text NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    revoked_at timestamp with time zone,
    revoked_by_principal_id uuid,
    CONSTRAINT delegations_capabilities_check CHECK ((cardinality(allowed_capabilities) > 0)),
    CONSTRAINT delegations_provenance_reference_check CHECK (((length(btrim(provenance_reference)) >= 1) AND (length(btrim(provenance_reference)) <= 500))),
    CONSTRAINT delegations_purpose_check CHECK (((length(btrim(purpose)) >= 1) AND (length(btrim(purpose)) <= 500))),
    CONSTRAINT delegations_revision_check CHECK ((revision > 0)),
    CONSTRAINT delegations_revocation_check CHECK ((((status = 'revoked'::text) AND (revoked_at IS NOT NULL) AND (revoked_by_principal_id IS NOT NULL)) OR ((status = 'active'::text) AND (revoked_at IS NULL) AND (revoked_by_principal_id IS NULL)))),
    CONSTRAINT delegations_self_check CHECK ((delegator_principal_id <> delegate_principal_id)),
    CONSTRAINT delegations_status_check CHECK ((status = ANY (ARRAY['active'::text, 'revoked'::text]))),
    CONSTRAINT delegations_window_check CHECK ((expires_at > not_before))
);

ALTER TABLE ONLY request_engine.delegations FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.delegations OWNER TO request_engine_schema_owner;

--
-- Name: discovery_booking_handoffs; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.discovery_booking_handoffs (
    id uuid DEFAULT uuidv7() NOT NULL,
    token_hash text NOT NULL,
    organization_id uuid NOT NULL,
    publication_id uuid NOT NULL,
    publication_revision bigint NOT NULL,
    mapping_id uuid NOT NULL,
    mapping_revision bigint NOT NULL,
    offering_version_id uuid NOT NULL,
    location_id uuid NOT NULL,
    selection jsonb NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    consumed_reservation_id uuid,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT discovery_booking_handoffs_mapping_revision_check CHECK ((mapping_revision > 0)),
    CONSTRAINT discovery_booking_handoffs_publication_revision_check CHECK ((publication_revision > 0)),
    CONSTRAINT discovery_booking_handoffs_selection_check CHECK ((jsonb_typeof(selection) = 'object'::text)),
    CONSTRAINT discovery_booking_handoffs_token_hash_check CHECK ((token_hash ~ '^[0-9a-f]{64}$'::text))
);

ALTER TABLE ONLY request_engine.discovery_booking_handoffs FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.discovery_booking_handoffs OWNER TO request_engine_schema_owner;

--
-- Name: discovery_publications; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.discovery_publications (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    offering_id uuid NOT NULL,
    location_id uuid NOT NULL,
    resource_id uuid,
    effective_during tstzrange NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    provider_visibility text DEFAULT 'hidden'::text NOT NULL,
    revision bigint DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT discovery_publications_effective_during_check CHECK ((NOT isempty(effective_during))),
    CONSTRAINT discovery_publications_effective_during_check1 CHECK ((lower(effective_during) IS NOT NULL)),
    CONSTRAINT discovery_publications_effective_during_check2 CHECK ((lower_inc(effective_during) AND (NOT upper_inc(effective_during)))),
    CONSTRAINT discovery_publications_provider_visibility_check CHECK ((provider_visibility = ANY (ARRAY['hidden'::text, 'public'::text]))),
    CONSTRAINT discovery_publications_public_provider_scope_ck CHECK (((provider_visibility <> 'public'::text) OR (resource_id IS NOT NULL))),
    CONSTRAINT discovery_publications_revision_check CHECK ((revision > 0)),
    CONSTRAINT discovery_publications_status_check CHECK ((status = ANY (ARRAY['active'::text, 'revoked'::text])))
);

ALTER TABLE ONLY request_engine.discovery_publications FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.discovery_publications OWNER TO request_engine_schema_owner;

--
-- Name: external_correlations; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.external_correlations (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    request_id uuid,
    correlation_kind text NOT NULL,
    provider_key text NOT NULL,
    external_key text NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT external_correlations_correlation_kind_check CHECK ((correlation_kind <> ''::text)),
    CONSTRAINT external_correlations_external_key_check CHECK ((external_key <> ''::text)),
    CONSTRAINT external_correlations_provider_key_check CHECK ((provider_key <> ''::text))
);


ALTER TABLE request_engine.external_correlations OWNER TO request_engine_schema_owner;

--
-- Name: global_identities; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.global_identities (
    id uuid DEFAULT uuidv7() NOT NULL,
    identity_kind text NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    evidence_ref text,
    created_authority_ref text NOT NULL,
    creation_reason text NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    retired_at timestamp with time zone,
    CONSTRAINT global_identities_check CHECK (((status = 'retired'::text) = (retired_at IS NOT NULL))),
    CONSTRAINT global_identities_created_authority_ref_check CHECK ((created_authority_ref <> ''::text)),
    CONSTRAINT global_identities_creation_reason_check CHECK ((creation_reason <> ''::text)),
    CONSTRAINT global_identities_identity_kind_check CHECK ((identity_kind = ANY (ARRAY['person'::text, 'organization'::text]))),
    CONSTRAINT global_identities_status_check CHECK ((status = ANY (ARRAY['active'::text, 'retired'::text])))
);


ALTER TABLE request_engine.global_identities OWNER TO request_engine_schema_owner;

--
-- Name: idempotency_records; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.idempotency_records (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    principal_id uuid NOT NULL,
    capability text NOT NULL,
    idempotency_key text NOT NULL,
    request_fingerprint text NOT NULL,
    status text DEFAULT 'in_progress'::text NOT NULL,
    result_data jsonb,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    completed_at timestamp with time zone,
    CONSTRAINT idempotency_records_capability_check CHECK ((capability <> ''::text)),
    CONSTRAINT idempotency_records_check CHECK (((status = 'completed'::text) = (completed_at IS NOT NULL))),
    CONSTRAINT idempotency_records_idempotency_key_check CHECK ((idempotency_key <> ''::text)),
    CONSTRAINT idempotency_records_request_fingerprint_check CHECK ((request_fingerprint <> ''::text)),
    CONSTRAINT idempotency_records_status_check CHECK ((status = ANY (ARRAY['in_progress'::text, 'completed'::text])))
);


ALTER TABLE request_engine.idempotency_records OWNER TO request_engine_schema_owner;

--
-- Name: identity_authorities; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.identity_authorities (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    kind text NOT NULL,
    issuer_or_environment text NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    configuration_ref text,
    revision bigint DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT identity_authorities_issuer_check CHECK ((length(btrim(issuer_or_environment)) > 0)),
    CONSTRAINT identity_authorities_kind_check CHECK ((length(btrim(kind)) > 0)),
    CONSTRAINT identity_authorities_revision_check CHECK ((revision > 0)),
    CONSTRAINT identity_authorities_status_check CHECK ((status = ANY (ARRAY['active'::text, 'disabled'::text])))
);


ALTER TABLE request_engine.identity_authorities OWNER TO request_engine_schema_owner;

--
-- Name: identity_bindings; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.identity_bindings (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    organization_id uuid,
    principal_id uuid NOT NULL,
    principal_plane text NOT NULL,
    identity_authority_id uuid NOT NULL,
    subject_id text NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    revision bigint DEFAULT 1 NOT NULL,
    last_seen_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    revoked_at timestamp with time zone,
    CONSTRAINT identity_bindings_last_seen_check CHECK (((last_seen_at IS NULL) OR (last_seen_at >= created_at))),
    CONSTRAINT identity_bindings_principal_plane_check CHECK ((principal_plane = ANY (ARRAY['tenant'::text, 'platform'::text]))),
    CONSTRAINT identity_bindings_revision_check CHECK ((revision > 0)),
    CONSTRAINT identity_bindings_revocation_check CHECK ((((status = 'revoked'::text) AND (revoked_at IS NOT NULL)) OR ((status <> 'revoked'::text) AND (revoked_at IS NULL)))),
    CONSTRAINT identity_bindings_scope_check CHECK ((((principal_plane = 'tenant'::text) AND (organization_id IS NOT NULL)) OR ((principal_plane = 'platform'::text) AND (organization_id IS NULL)))),
    CONSTRAINT identity_bindings_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'active'::text, 'suspended'::text, 'revoked'::text]))),
    CONSTRAINT identity_bindings_subject_check CHECK ((length(btrim(subject_id)) > 0))
);

ALTER TABLE ONLY request_engine.identity_bindings FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.identity_bindings OWNER TO request_engine_schema_owner;

--
-- Name: identity_exchange_candidates; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.identity_exchange_candidates (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    portable_party_id uuid NOT NULL,
    kind text NOT NULL,
    authority text NOT NULL,
    fingerprint text NOT NULL,
    created_by_principal_id uuid NOT NULL,
    expires_at timestamp with time zone DEFAULT (clock_timestamp() + '00:10:00'::interval) NOT NULL,
    consumed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT identity_exchange_candidate_authority_ck CHECK ((((kind = 'cedula'::text) AND (authority = 'DO:JCE'::text)) OR ((kind = 'passport'::text) AND (authority ~ '^[A-Z]{2}$'::text)) OR ((kind = 'rnc'::text) AND (authority = 'DO:DGII'::text)))),
    CONSTRAINT identity_exchange_candidates_fingerprint_check CHECK ((fingerprint ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT identity_exchange_candidates_kind_check CHECK ((kind = ANY (ARRAY['cedula'::text, 'passport'::text, 'rnc'::text])))
);

ALTER TABLE ONLY request_engine.identity_exchange_candidates FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.identity_exchange_candidates OWNER TO request_engine_schema_owner;

--
-- Name: identity_link_facts; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.identity_link_facts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    actor_principal_id uuid NOT NULL,
    organization_id uuid NOT NULL,
    capability_key text NOT NULL,
    action text NOT NULL,
    intent_id uuid,
    target_authority_id uuid NOT NULL,
    subject_id text,
    binding_id uuid,
    nonce_digest text NOT NULL,
    provenance_reference text NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT identity_link_facts_action_check CHECK ((action = ANY (ARRAY['intent_created'::text, 'linked'::text, 'conflict'::text]))),
    CONSTRAINT identity_link_facts_capability_check CHECK ((capability_key = 'identity.link_self'::text))
);

ALTER TABLE ONLY request_engine.identity_link_facts FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.identity_link_facts OWNER TO request_engine_schema_owner;

--
-- Name: identity_link_intents; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.identity_link_intents (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    organization_id uuid NOT NULL,
    actor_principal_id uuid NOT NULL,
    actor_binding_id uuid NOT NULL,
    target_authority_id uuid NOT NULL,
    actor_binding_revision bigint NOT NULL,
    nonce_digest text NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    consumed_at timestamp with time zone,
    resulting_binding_id uuid,
    provenance_reference text NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT identity_link_intents_actor_binding_revision_check CHECK ((actor_binding_revision >= 1)),
    CONSTRAINT identity_link_intents_expiry_check CHECK ((expires_at > created_at)),
    CONSTRAINT identity_link_intents_nonce_digest_check CHECK ((nonce_digest ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT identity_link_intents_provenance_reference_check CHECK (((length(btrim(provenance_reference)) >= 1) AND (length(btrim(provenance_reference)) <= 400))),
    CONSTRAINT identity_link_intents_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'consumed'::text, 'revoked'::text, 'expired'::text])))
);

ALTER TABLE ONLY request_engine.identity_link_intents FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.identity_link_intents OWNER TO request_engine_schema_owner;

--
-- Name: identity_recovery_cases; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.identity_recovery_cases (
    id uuid NOT NULL,
    target_native_identity_id uuid NOT NULL,
    requester_principal_id uuid NOT NULL,
    approver_principal_id uuid,
    status text DEFAULT 'requested'::text NOT NULL,
    delivery_status text DEFAULT 'pending'::text NOT NULL,
    reason_code text NOT NULL,
    evidence_reference text NOT NULL,
    delivery_destination_reference text NOT NULL,
    recovery_intent_id uuid,
    issuance_generation integer DEFAULT 0 NOT NULL,
    approval_expires_at timestamp with time zone,
    proof_expires_at timestamp with time zone,
    revision bigint DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    approved_at timestamp with time zone,
    issued_at timestamp with time zone,
    consumed_at timestamp with time zone,
    revoked_at timestamp with time zone,
    revoke_reason_code text,
    CONSTRAINT identity_recovery_cases_approver_check CHECK (((approver_principal_id IS NULL) OR (approver_principal_id <> requester_principal_id))),
    CONSTRAINT identity_recovery_cases_delivery_status_check CHECK ((delivery_status = ANY (ARRAY['pending'::text, 'sending'::text, 'delivered'::text, 'unknown'::text, 'failed'::text]))),
    CONSTRAINT identity_recovery_cases_destination_check CHECK (((length(btrim(delivery_destination_reference)) >= 1) AND (length(btrim(delivery_destination_reference)) <= 200))),
    CONSTRAINT identity_recovery_cases_evidence_check CHECK (((length(btrim(evidence_reference)) >= 1) AND (length(btrim(evidence_reference)) <= 400))),
    CONSTRAINT identity_recovery_cases_generation_check CHECK ((issuance_generation >= 0)),
    CONSTRAINT identity_recovery_cases_reason_check CHECK (((length(btrim(reason_code)) >= 1) AND (length(btrim(reason_code)) <= 80))),
    CONSTRAINT identity_recovery_cases_revision_check CHECK ((revision >= 1)),
    CONSTRAINT identity_recovery_cases_state_check CHECK ((((status = 'requested'::text) AND (approver_principal_id IS NULL) AND (approved_at IS NULL) AND (recovery_intent_id IS NULL) AND (issued_at IS NULL) AND (consumed_at IS NULL) AND (revoked_at IS NULL)) OR ((status = 'approved'::text) AND (approver_principal_id IS NOT NULL) AND (approved_at IS NOT NULL) AND (approval_expires_at IS NOT NULL) AND (recovery_intent_id IS NULL) AND (issued_at IS NULL) AND (consumed_at IS NULL) AND (revoked_at IS NULL)) OR ((status = 'issued'::text) AND (approver_principal_id IS NOT NULL) AND (approved_at IS NOT NULL) AND (recovery_intent_id IS NOT NULL) AND (issued_at IS NOT NULL) AND (proof_expires_at IS NOT NULL) AND (consumed_at IS NULL) AND (revoked_at IS NULL)) OR ((status = 'consumed'::text) AND (recovery_intent_id IS NOT NULL) AND (issued_at IS NOT NULL) AND (consumed_at IS NOT NULL) AND (revoked_at IS NULL)) OR ((status = 'revoked'::text) AND (revoked_at IS NOT NULL) AND (revoke_reason_code IS NOT NULL)))),
    CONSTRAINT identity_recovery_cases_status_check CHECK ((status = ANY (ARRAY['requested'::text, 'approved'::text, 'issued'::text, 'consumed'::text, 'revoked'::text])))
);


ALTER TABLE request_engine.identity_recovery_cases OWNER TO request_engine_schema_owner;

--
-- Name: identity_recovery_delivery_tickets; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.identity_recovery_delivery_tickets (
    id uuid NOT NULL,
    case_id uuid NOT NULL,
    generation integer NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    secret_reference text NOT NULL,
    secret_digest text NOT NULL,
    destination_reference text CONSTRAINT identity_recovery_delivery_ticke_destination_reference_not_null NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    claim_token uuid,
    lease_until timestamp with time zone,
    attempt_count integer DEFAULT 0 NOT NULL,
    max_attempts integer DEFAULT 8 NOT NULL,
    next_attempt_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    last_error_class text,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    delivered_at timestamp with time zone,
    CONSTRAINT identity_recovery_delivery_tickets_attempts_check CHECK (((attempt_count >= 0) AND ((max_attempts >= 1) AND (max_attempts <= 100)))),
    CONSTRAINT identity_recovery_delivery_tickets_destination_check CHECK (((length(btrim(destination_reference)) >= 1) AND (length(btrim(destination_reference)) <= 200))),
    CONSTRAINT identity_recovery_delivery_tickets_digest_check CHECK ((secret_digest ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT identity_recovery_delivery_tickets_generation_check CHECK ((generation >= 1)),
    CONSTRAINT identity_recovery_delivery_tickets_lease_check CHECK ((((status = 'sending'::text) AND (claim_token IS NOT NULL) AND (lease_until IS NOT NULL)) OR ((status <> 'sending'::text) AND (claim_token IS NULL) AND (lease_until IS NULL)))),
    CONSTRAINT identity_recovery_delivery_tickets_secret_check CHECK (((length(btrim(secret_reference)) >= 1) AND (length(btrim(secret_reference)) <= 400))),
    CONSTRAINT identity_recovery_delivery_tickets_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'sending'::text, 'delivered'::text, 'unknown'::text, 'failed'::text, 'cancelled'::text])))
);


ALTER TABLE request_engine.identity_recovery_delivery_tickets OWNER TO request_engine_schema_owner;

--
-- Name: identity_recovery_issuance_reservations; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.identity_recovery_issuance_reservations (
    case_id uuid NOT NULL,
    generation integer NOT NULL,
    idempotency_key_digest text CONSTRAINT identity_recovery_issuance_rese_idempotency_key_digest_not_null NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT identity_recovery_issuance_reservations_digest_check CHECK ((idempotency_key_digest ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT identity_recovery_issuance_reservations_generation_check CHECK ((generation >= 1))
);


ALTER TABLE request_engine.identity_recovery_issuance_reservations OWNER TO request_engine_schema_owner;

--
-- Name: initial_controller_policies; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.initial_controller_policies (
    policy_key text NOT NULL,
    revision integer NOT NULL,
    grants jsonb NOT NULL,
    CONSTRAINT initial_controller_policies_grants_check CHECK (((jsonb_typeof(grants) = 'array'::text) AND (jsonb_array_length(grants) > 0))),
    CONSTRAINT initial_controller_policies_revision_check CHECK ((revision > 0))
);


ALTER TABLE request_engine.initial_controller_policies OWNER TO request_engine_schema_owner;

--
-- Name: integration_governance_facts; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.integration_governance_facts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    organization_id uuid NOT NULL,
    integration_principal_id uuid NOT NULL,
    actor_principal_id uuid,
    actor_authority_revision bigint,
    operation text NOT NULL,
    provenance_reference text NOT NULL,
    policy_version text DEFAULT 'integration-governance/1'::text NOT NULL,
    authority_revision bigint NOT NULL,
    snapshot jsonb NOT NULL,
    occurred_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT integration_facts_attribution_check CHECK ((((operation = 'legacy_snapshot'::text) AND (actor_principal_id IS NULL) AND (actor_authority_revision IS NULL)) OR ((operation <> 'legacy_snapshot'::text) AND (actor_principal_id IS NOT NULL) AND (actor_authority_revision IS NOT NULL) AND (actor_authority_revision > 0)))),
    CONSTRAINT integration_governance_facts_authority_revision_check CHECK ((authority_revision > 0)),
    CONSTRAINT integration_governance_facts_operation_check CHECK ((operation = ANY (ARRAY['provision'::text, 'authority_replace'::text, 'status_transition'::text, 'credential_rotate'::text, 'legacy_snapshot'::text]))),
    CONSTRAINT integration_governance_facts_provenance_reference_check CHECK (((length(btrim(provenance_reference)) >= 1) AND (length(btrim(provenance_reference)) <= 500))),
    CONSTRAINT integration_governance_facts_snapshot_check CHECK ((jsonb_typeof(snapshot) = 'object'::text))
);

ALTER TABLE ONLY request_engine.integration_governance_facts FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.integration_governance_facts OWNER TO request_engine_schema_owner;

--
-- Name: live_capacity_projection_policies; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.live_capacity_projection_policies (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    service_queue_id uuid NOT NULL,
    resource_id uuid NOT NULL,
    location_id uuid NOT NULL,
    active boolean DEFAULT true NOT NULL,
    revision bigint DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT live_capacity_projection_policies_revision_check CHECK ((revision > 0))
);

ALTER TABLE ONLY request_engine.live_capacity_projection_policies FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.live_capacity_projection_policies OWNER TO request_engine_schema_owner;

--
-- Name: live_capacity_workload_estimate_policies; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.live_capacity_workload_estimate_policies (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid CONSTRAINT live_capacity_workload_estimate_polici_organization_id_not_null NOT NULL,
    workload_classification_id uuid CONSTRAINT live_capacity_workload_esti_workload_classification_id_not_null NOT NULL,
    duration_seconds integer CONSTRAINT live_capacity_workload_estimate_polic_duration_seconds_not_null NOT NULL,
    active boolean DEFAULT true NOT NULL,
    revision bigint DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT live_capacity_workload_estimate_policies_duration_seconds_check CHECK ((duration_seconds > 0)),
    CONSTRAINT live_capacity_workload_estimate_policies_revision_check CHECK ((revision > 0))
);

ALTER TABLE ONLY request_engine.live_capacity_workload_estimate_policies FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.live_capacity_workload_estimate_policies OWNER TO request_engine_schema_owner;

--
-- Name: location_hours_exceptions; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.location_hours_exceptions (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    location_id uuid NOT NULL,
    during tstzrange NOT NULL,
    exception_kind text NOT NULL,
    reason text,
    active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT location_hours_exceptions_during_check CHECK ((NOT isempty(during))),
    CONSTRAINT location_hours_exceptions_during_check1 CHECK (((lower(during) IS NOT NULL) AND (upper(during) IS NOT NULL))),
    CONSTRAINT location_hours_exceptions_during_check2 CHECK ((lower_inc(during) AND (NOT upper_inc(during)))),
    CONSTRAINT location_hours_exceptions_exception_kind_check CHECK ((exception_kind = ANY (ARRAY['available'::text, 'unavailable'::text])))
);

ALTER TABLE ONLY request_engine.location_hours_exceptions FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.location_hours_exceptions OWNER TO request_engine_schema_owner;

--
-- Name: location_operational_hours; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.location_operational_hours (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    location_id uuid NOT NULL,
    weekday smallint NOT NULL,
    local_start time without time zone NOT NULL,
    local_end time without time zone NOT NULL,
    valid_from date,
    valid_until date,
    active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT location_operational_hours_check CHECK ((local_start < local_end)),
    CONSTRAINT location_operational_hours_check1 CHECK (((valid_until IS NULL) OR (valid_from IS NULL) OR (valid_until >= valid_from))),
    CONSTRAINT location_operational_hours_weekday_check CHECK (((weekday >= 0) AND (weekday <= 6)))
);

ALTER TABLE ONLY request_engine.location_operational_hours FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.location_operational_hours OWNER TO request_engine_schema_owner;

--
-- Name: location_public_contact_endpoints; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.location_public_contact_endpoints (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    location_id uuid NOT NULL,
    channel text NOT NULL,
    normalized_value text NOT NULL,
    label text,
    active boolean DEFAULT true NOT NULL,
    is_public boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT location_public_contact_endpoints_channel_check CHECK ((channel = ANY (ARRAY['phone'::text, 'whatsapp'::text, 'email'::text]))),
    CONSTRAINT location_public_contact_endpoints_label_check CHECK (((label IS NULL) OR (btrim(label) <> ''::text))),
    CONSTRAINT location_public_contact_endpoints_normalized_value_check CHECK ((normalized_value <> ''::text))
);

ALTER TABLE ONLY request_engine.location_public_contact_endpoints FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.location_public_contact_endpoints OWNER TO request_engine_schema_owner;

--
-- Name: locations; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.locations (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    location_key text NOT NULL,
    display_name text NOT NULL,
    timezone text NOT NULL,
    public_data jsonb DEFAULT '{}'::jsonb NOT NULL,
    active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    address_line1 text,
    address_line2 text,
    locality text,
    administrative_area text,
    postal_code text,
    country_code text,
    latitude numeric(9,6),
    longitude numeric(9,6),
    geocoding_source text,
    geocoded_at timestamp with time zone,
    operational_revision bigint DEFAULT 1 NOT NULL,
    CONSTRAINT locations_address_line1_ck CHECK (((address_line1 IS NULL) OR (btrim(address_line1) <> ''::text))),
    CONSTRAINT locations_coordinate_pair_ck CHECK (((latitude IS NULL) = (longitude IS NULL))),
    CONSTRAINT locations_country_code_ck CHECK (((country_code IS NULL) OR (country_code ~ '^[A-Z]{2}$'::text))),
    CONSTRAINT locations_display_name_check CHECK ((display_name <> ''::text)),
    CONSTRAINT locations_latitude_ck CHECK (((latitude IS NULL) OR ((latitude >= ('-90'::integer)::numeric) AND (latitude <= (90)::numeric)))),
    CONSTRAINT locations_location_key_check CHECK ((location_key <> ''::text)),
    CONSTRAINT locations_longitude_ck CHECK (((longitude IS NULL) OR ((longitude >= ('-180'::integer)::numeric) AND (longitude <= (180)::numeric)))),
    CONSTRAINT locations_operational_revision_ck CHECK ((operational_revision > 0)),
    CONSTRAINT locations_public_data_check CHECK ((jsonb_typeof(public_data) = 'object'::text)),
    CONSTRAINT locations_timezone_check CHECK ((timezone <> ''::text))
);


ALTER TABLE request_engine.locations OWNER TO request_engine_schema_owner;

--
-- Name: native_credentials; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.native_credentials (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    native_identity_id uuid NOT NULL,
    kind text DEFAULT 'password'::text NOT NULL,
    verifier text NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    revision bigint DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    rotated_at timestamp with time zone,
    revoked_at timestamp with time zone,
    last_used_at timestamp with time zone,
    CONSTRAINT native_credentials_kind_check CHECK ((kind = 'password'::text)),
    CONSTRAINT native_credentials_revision_check CHECK ((revision > 0)),
    CONSTRAINT native_credentials_revocation_check CHECK ((((status = 'revoked'::text) AND (revoked_at IS NOT NULL)) OR ((status = 'active'::text) AND (revoked_at IS NULL)))),
    CONSTRAINT native_credentials_status_check CHECK ((status = ANY (ARRAY['active'::text, 'revoked'::text]))),
    CONSTRAINT native_credentials_verifier_check CHECK (((length(verifier) > 32) AND ((verifier ~~ 'scrypt$%'::text) OR (verifier ~~ '$argon2id$%'::text))))
);


ALTER TABLE request_engine.native_credentials OWNER TO request_engine_schema_owner;

--
-- Name: native_identities; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.native_identities (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    identity_authority_id uuid NOT NULL,
    login_handle text NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    session_epoch bigint DEFAULT 1 NOT NULL,
    revision bigint DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    disabled_at timestamp with time zone,
    CONSTRAINT native_identities_disabled_check CHECK ((((status = 'disabled'::text) AND (disabled_at IS NOT NULL)) OR ((status = 'active'::text) AND (disabled_at IS NULL)))),
    CONSTRAINT native_identities_handle_check CHECK (((login_handle = btrim(login_handle)) AND ((length(login_handle) >= 1) AND (length(login_handle) <= 320)))),
    CONSTRAINT native_identities_revision_check CHECK ((revision > 0)),
    CONSTRAINT native_identities_session_epoch_check CHECK ((session_epoch > 0)),
    CONSTRAINT native_identities_status_check CHECK ((status = ANY (ARRAY['active'::text, 'disabled'::text])))
);


ALTER TABLE request_engine.native_identities OWNER TO request_engine_schema_owner;

--
-- Name: native_identity_recovery_facts; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.native_identity_recovery_facts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    native_identity_id uuid NOT NULL,
    event_kind text NOT NULL,
    recovery_epoch bigint NOT NULL,
    recovery_method text NOT NULL,
    correlation_id uuid,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT native_identity_recovery_facts_epoch_check CHECK ((recovery_epoch > 0)),
    CONSTRAINT native_identity_recovery_facts_kind_check CHECK ((event_kind = ANY (ARRAY['recovery_started'::text, 'recovery_completed'::text])))
);


ALTER TABLE request_engine.native_identity_recovery_facts OWNER TO request_engine_schema_owner;

--
-- Name: native_identity_recovery_state; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.native_identity_recovery_state (
    native_identity_id uuid NOT NULL,
    state text NOT NULL,
    recovery_epoch bigint NOT NULL,
    revision bigint DEFAULT 1 NOT NULL,
    last_recovered_at timestamp with time zone NOT NULL,
    last_recovery_method text NOT NULL,
    completed_at timestamp with time zone,
    CONSTRAINT native_identity_recovery_state_completion_check CHECK ((((state = 'recovery_restricted'::text) AND (completed_at IS NULL)) OR ((state = 'normal'::text) AND (completed_at IS NOT NULL)))),
    CONSTRAINT native_identity_recovery_state_epoch_check CHECK ((recovery_epoch > 0)),
    CONSTRAINT native_identity_recovery_state_revision_check CHECK ((revision > 0)),
    CONSTRAINT native_identity_recovery_state_state_check CHECK ((state = ANY (ARRAY['recovery_restricted'::text, 'normal'::text])))
);


ALTER TABLE request_engine.native_identity_recovery_state OWNER TO request_engine_schema_owner;

--
-- Name: native_recovery_address_facts; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.native_recovery_address_facts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    native_identity_id uuid NOT NULL,
    recovery_address_id uuid NOT NULL,
    event_kind text NOT NULL,
    correlation_id uuid,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT native_recovery_address_facts_kind_check CHECK ((event_kind = ANY (ARRAY['verification_requested'::text, 'address_verified'::text, 'address_revoked'::text, 'recovery_requested'::text])))
);


ALTER TABLE request_engine.native_recovery_address_facts OWNER TO request_engine_schema_owner;

--
-- Name: native_recovery_address_verifications; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.native_recovery_address_verifications (
    id uuid NOT NULL,
    recovery_address_id uuid CONSTRAINT native_recovery_address_verificati_recovery_address_id_not_null NOT NULL,
    token_digest bytea NOT NULL,
    token_fingerprint text CONSTRAINT native_recovery_address_verification_token_fingerprint_not_null NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    consumed_at timestamp with time zone,
    revoked_at timestamp with time zone,
    CONSTRAINT native_recovery_address_verifications_digest_check CHECK ((octet_length(token_digest) = 32)),
    CONSTRAINT native_recovery_address_verifications_fingerprint_check CHECK ((token_fingerprint ~ '^[0-9a-f]{16}$'::text)),
    CONSTRAINT native_recovery_address_verifications_lifecycle_check CHECK ((((status = 'pending'::text) AND (consumed_at IS NULL) AND (revoked_at IS NULL)) OR ((status = 'consumed'::text) AND (consumed_at IS NOT NULL) AND (revoked_at IS NULL)) OR ((status = 'revoked'::text) AND (revoked_at IS NOT NULL)))),
    CONSTRAINT native_recovery_address_verifications_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'consumed'::text, 'revoked'::text]))),
    CONSTRAINT native_recovery_address_verifications_time_check CHECK ((expires_at > created_at))
);


ALTER TABLE request_engine.native_recovery_address_verifications OWNER TO request_engine_schema_owner;

--
-- Name: native_recovery_addresses; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.native_recovery_addresses (
    id uuid NOT NULL,
    native_identity_id uuid NOT NULL,
    kind text NOT NULL,
    normalized_address text NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    revision bigint DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    verified_at timestamp with time zone,
    revoked_at timestamp with time zone,
    CONSTRAINT native_recovery_addresses_kind_check CHECK ((kind = 'email'::text)),
    CONSTRAINT native_recovery_addresses_lifecycle_check CHECK ((((status = 'pending'::text) AND (verified_at IS NULL) AND (revoked_at IS NULL)) OR ((status = 'verified'::text) AND (verified_at IS NOT NULL) AND (revoked_at IS NULL)) OR ((status = 'revoked'::text) AND (revoked_at IS NOT NULL)))),
    CONSTRAINT native_recovery_addresses_revision_check CHECK ((revision > 0)),
    CONSTRAINT native_recovery_addresses_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'verified'::text, 'revoked'::text])))
);


ALTER TABLE request_engine.native_recovery_addresses OWNER TO request_engine_schema_owner;

--
-- Name: native_recovery_delivery_facts; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.native_recovery_delivery_facts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    request_id uuid NOT NULL,
    native_identity_id uuid NOT NULL,
    recovery_address_id uuid NOT NULL,
    generation integer NOT NULL,
    event_kind text NOT NULL,
    error_class text,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT native_recovery_delivery_facts_error_check CHECK (((error_class IS NULL) OR ((length(btrim(error_class)) >= 1) AND (length(btrim(error_class)) <= 80)))),
    CONSTRAINT native_recovery_delivery_facts_generation_check CHECK ((generation >= 0)),
    CONSTRAINT native_recovery_delivery_facts_kind_check CHECK ((event_kind = ANY (ARRAY['staged'::text, 'retry_scheduled'::text, 'delivered'::text, 'delivery_unknown'::text, 'delivery_failed'::text])))
);


ALTER TABLE request_engine.native_recovery_delivery_facts OWNER TO request_engine_schema_owner;

--
-- Name: native_recovery_delivery_requests; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.native_recovery_delivery_requests (
    id uuid NOT NULL,
    native_identity_id uuid NOT NULL,
    recovery_address_id uuid NOT NULL,
    destination_reference text CONSTRAINT native_recovery_delivery_request_destination_reference_not_null NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    generation integer DEFAULT 0 NOT NULL,
    recovery_intent_id uuid,
    secret_reference text,
    secret_digest text,
    proof_expires_at timestamp with time zone,
    request_expires_at timestamp with time zone NOT NULL,
    claim_token uuid,
    lease_until timestamp with time zone,
    attempt_count integer DEFAULT 0 NOT NULL,
    max_attempts integer DEFAULT 8 NOT NULL,
    next_attempt_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    last_error_class text,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    delivered_at timestamp with time zone,
    CONSTRAINT native_recovery_delivery_requests_attempts_check CHECK (((attempt_count >= 0) AND ((max_attempts >= 1) AND (max_attempts <= 100)))),
    CONSTRAINT native_recovery_delivery_requests_destination_check CHECK (((length(btrim(destination_reference)) >= 3) AND (length(btrim(destination_reference)) <= 320))),
    CONSTRAINT native_recovery_delivery_requests_expiry_check CHECK ((request_expires_at > created_at)),
    CONSTRAINT native_recovery_delivery_requests_generation_check CHECK ((generation >= 0)),
    CONSTRAINT native_recovery_delivery_requests_lease_check CHECK ((((status = 'sending'::text) AND (claim_token IS NOT NULL) AND (lease_until IS NOT NULL)) OR ((status <> 'sending'::text) AND (claim_token IS NULL) AND (lease_until IS NULL)))),
    CONSTRAINT native_recovery_delivery_requests_secret_check CHECK ((((secret_reference IS NULL) AND (secret_digest IS NULL) AND (recovery_intent_id IS NULL) AND (proof_expires_at IS NULL)) OR ((secret_reference IS NOT NULL) AND ((length(btrim(secret_reference)) >= 1) AND (length(btrim(secret_reference)) <= 400)) AND (secret_digest ~ '^[0-9a-f]{64}$'::text) AND (recovery_intent_id IS NOT NULL) AND (proof_expires_at IS NOT NULL)))),
    CONSTRAINT native_recovery_delivery_requests_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'sending'::text, 'delivered'::text, 'unknown'::text, 'failed'::text, 'cancelled'::text])))
);


ALTER TABLE request_engine.native_recovery_delivery_requests OWNER TO request_engine_schema_owner;

--
-- Name: native_recovery_intents; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.native_recovery_intents (
    id uuid NOT NULL,
    native_identity_id uuid NOT NULL,
    token_digest bytea NOT NULL,
    token_fingerprint text NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    consumed_at timestamp with time zone,
    revoked_at timestamp with time zone,
    CONSTRAINT native_recovery_digest_check CHECK ((octet_length(token_digest) = 32)),
    CONSTRAINT native_recovery_expiry_check CHECK ((expires_at > created_at)),
    CONSTRAINT native_recovery_fingerprint_check CHECK ((token_fingerprint ~ '^[0-9a-f]{16}$'::text)),
    CONSTRAINT native_recovery_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'consumed'::text, 'revoked'::text]))),
    CONSTRAINT native_recovery_terminal_check CHECK ((((status = 'pending'::text) AND (consumed_at IS NULL) AND (revoked_at IS NULL)) OR ((status = 'consumed'::text) AND (consumed_at IS NOT NULL) AND (revoked_at IS NULL)) OR ((status = 'revoked'::text) AND (consumed_at IS NULL) AND (revoked_at IS NOT NULL))))
);


ALTER TABLE request_engine.native_recovery_intents OWNER TO request_engine_schema_owner;

--
-- Name: native_sessions; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.native_sessions (
    id uuid NOT NULL,
    native_identity_id uuid NOT NULL,
    password_credential_id uuid,
    token_digest bytea NOT NULL,
    token_fingerprint text NOT NULL,
    session_epoch bigint NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    last_seen_at timestamp with time zone,
    revoked_at timestamp with time zone,
    revocation_reason text,
    last_authenticated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    webauthn_credential_id uuid,
    authentication_methods text[] DEFAULT ARRAY['password'::text] NOT NULL,
    authentication_assurance text DEFAULT 'single_factor'::text NOT NULL,
    user_verified boolean DEFAULT false NOT NULL,
    recovery_derived boolean DEFAULT false NOT NULL,
    CONSTRAINT native_sessions_assurance_check CHECK ((authentication_assurance = ANY (ARRAY['single_factor'::text, 'mfa'::text, 'phishing_resistant'::text, 'recovery'::text]))),
    CONSTRAINT native_sessions_assurance_derivation_check CHECK ((authentication_assurance =
CASE
    WHEN (recovery_derived OR ('recovery_code'::text = ANY (authentication_methods))) THEN 'recovery'::text
    WHEN (('webauthn'::text = ANY (authentication_methods)) AND user_verified) THEN 'phishing_resistant'::text
    WHEN ((cardinality(authentication_methods) -
    CASE
        WHEN ('recovery_code'::text = ANY (authentication_methods)) THEN 1
        ELSE 0
    END) >= 2) THEN 'mfa'::text
    ELSE 'single_factor'::text
END)),
    CONSTRAINT native_sessions_digest_check CHECK ((octet_length(token_digest) = 32)),
    CONSTRAINT native_sessions_epoch_check CHECK ((session_epoch > 0)),
    CONSTRAINT native_sessions_expiry_check CHECK ((expires_at > created_at)),
    CONSTRAINT native_sessions_fingerprint_check CHECK ((token_fingerprint ~ '^[0-9a-f]{16}$'::text)),
    CONSTRAINT native_sessions_initial_authenticator_check CHECK (((password_credential_id IS NOT NULL) <> (webauthn_credential_id IS NOT NULL))),
    CONSTRAINT native_sessions_methods_check CHECK (((cardinality(authentication_methods) >= 1) AND (authentication_methods <@ ARRAY['password'::text, 'webauthn'::text, 'totp'::text, 'recovery_code'::text]))),
    CONSTRAINT native_sessions_phishing_check CHECK (((authentication_assurance <> 'phishing_resistant'::text) OR (user_verified AND ('webauthn'::text = ANY (authentication_methods))))),
    CONSTRAINT native_sessions_recovery_assurance_check CHECK (((authentication_assurance = 'recovery'::text) = recovery_derived)),
    CONSTRAINT native_sessions_recovery_check CHECK ((recovery_derived = ('recovery_code'::text = ANY (authentication_methods)))),
    CONSTRAINT native_sessions_revocation_check CHECK ((((status = 'revoked'::text) AND (revoked_at IS NOT NULL)) OR ((status = 'active'::text) AND (revoked_at IS NULL) AND (revocation_reason IS NULL)))),
