            v_actor:=NULLIF(current_setting('request_engine.authenticated_principal_id',true),'')::uuid;
            v_revision:=NULLIF(current_setting('request_engine.authority_revision',true),'')::bigint;
            IF v_actor IS NULL OR NOT EXISTS(
                SELECT 1 FROM request_engine.principals p
                JOIN request_engine.principal_authority_grants g ON g.principal_id=p.id
                WHERE p.id=v_actor AND p.principal_plane='platform'
                  AND p.principal_kind='human' AND p.active
                  AND p.authority_revision=v_revision
                  AND g.principal_plane='platform' AND g.authority_plane='platform'
                  AND g.capability_key='platform.organization.read' AND g.status='active'
            ) THEN
                RAISE EXCEPTION 'Current Platform Owner may not inspect adoption requests'
                    USING ERRCODE='42501';
            END IF;
            RETURN QUERY SELECT r.id,r.organization_id,r.controller_principal_id,
                r.source_policy_key,r.target_policy_key,r.expected_authority_revision,
                r.status,r.revision,r.created_at,r.expires_at
              FROM request_engine.controller_policy_adoption_requests r
             WHERE r.status='pending' AND r.expires_at>clock_timestamp()
               AND (p_request_id IS NULL OR r.id=p_request_id)
               AND (p_after IS NULL OR r.id>p_after)
             ORDER BY r.id LIMIT p_limit;
        END $$;


ALTER FUNCTION request_platform.list_controller_policy_adoptions(p_after uuid, p_limit integer, p_request_id uuid) OWNER TO request_platform_definer;

--
-- Name: managed_oidc_projection_matches(text, text, text, bigint); Type: FUNCTION; Schema: request_platform; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_platform.managed_oidc_projection_matches(p_issuer text, p_jwks_uri text, p_audience text, p_revision bigint) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
            SELECT EXISTS (
                SELECT 1
                  FROM request_engine.identity_authorities AS authority
                 WHERE authority.kind = 'oidc'
                   AND authority.issuer_or_environment = p_issuer
                   AND authority.status = 'active'
                   AND authority.configuration_ref = jsonb_build_object(
                       'jwks_uri', p_jwks_uri,
                       'audience', p_audience,
                       'managed_configuration_revision', p_revision
                   )::text
            )
        $$;


ALTER FUNCTION request_platform.managed_oidc_projection_matches(p_issuer text, p_jwks_uri text, p_audience text, p_revision bigint) OWNER TO request_engine_schema_owner;

--
-- Name: mark_platform_secret_backend_applied(uuid, integer); Type: FUNCTION; Schema: request_platform; Owner: request_platform_control_definer
--

CREATE FUNCTION request_platform.mark_platform_secret_backend_applied(p_operation_id uuid, p_applied_backend_version integer) RETURNS TABLE(operation_id uuid, operation_kind text, binding_id uuid, secret_id uuid, purpose text, backend text, expected_binding_revision bigint, expected_backend_version integer, applied_backend_version integer, operation_state text, result_binding_id uuid, result_binding_revision bigint, result_binding_status text)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
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
        $$;


ALTER FUNCTION request_platform.mark_platform_secret_backend_applied(p_operation_id uuid, p_applied_backend_version integer) OWNER TO request_platform_control_definer;

--
-- Name: native_identity_ready_for_platform_owner(uuid, uuid); Type: FUNCTION; Schema: request_platform; Owner: request_platform_control_definer
--

CREATE FUNCTION request_platform.native_identity_ready_for_platform_owner(p_identity_authority_id uuid, p_native_identity_id uuid) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
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
                   AND NOT EXISTS (
                       SELECT 1
                         FROM request_auth.read_native_recovery_readiness(identity.id) recovery
                        WHERE recovery.recovery_state <> 'normal'
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


ALTER FUNCTION request_platform.native_identity_ready_for_platform_owner(p_identity_authority_id uuid, p_native_identity_id uuid) OWNER TO request_platform_control_definer;

--
-- Name: prepare_identity_recovery_issue(uuid, bigint, text, text); Type: FUNCTION; Schema: request_platform; Owner: request_platform_control_definer
--

CREATE FUNCTION request_platform.prepare_identity_recovery_issue(p_case_id uuid, p_expected_revision bigint, p_idempotency_key_digest text, p_intent_digest text) RETURNS TABLE(replayed boolean, case_id uuid, target_native_identity_id uuid, status text, delivery_status text, revision bigint, issuance_generation integer, approval_expires_at timestamp with time zone, proof_expires_at timestamp with time zone, created_at timestamp with time zone, approved_at timestamp with time zone, issued_at timestamp with time zone, consumed_at timestamp with time zone, revoked_at timestamp with time zone)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $_$
        DECLARE
            v_actor_id uuid;
            v_actor_method text;
            v_correlation_id uuid;
            v_replay record;
            v_case record;
            v_reserved integer;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
            IF p_case_id IS NULL OR p_expected_revision IS NULL
               OR p_expected_revision < 1
               OR p_idempotency_key_digest IS NULL
               OR p_idempotency_key_digest !~ '^[0-9a-f]{64}$'
               OR p_intent_digest IS NULL
               OR p_intent_digest !~ '^[0-9a-f]{64}$' THEN
                RAISE EXCEPTION 'Identity recovery issuance input is invalid'
                    USING ERRCODE = '22023';
            END IF;

            SELECT actor_id, actor_method, correlation_id
              INTO v_actor_id, v_actor_method, v_correlation_id
              FROM request_platform.assert_platform_identity_actor('platform.identity.recover');

            SELECT fact.case_id, fact.intent_digest
              INTO v_replay
              FROM request_engine.platform_identity_recovery_facts AS fact
             WHERE fact.actor_principal_id = v_actor_id
               AND fact.action = 'issue'
               AND fact.idempotency_key_digest = p_idempotency_key_digest;
            IF FOUND THEN
                IF v_replay.intent_digest <> p_intent_digest THEN
                    RAISE EXCEPTION
                        'Idempotency key was already used for another recovery issuance'
                        USING ERRCODE = '23505';
                END IF;
                RETURN QUERY SELECT
                    true,
                    recovery_case.id,
                    recovery_case.target_native_identity_id,
                    recovery_case.status,
                    recovery_case.delivery_status,
                    recovery_case.revision,
                    recovery_case.issuance_generation,
                    recovery_case.approval_expires_at,
                    recovery_case.proof_expires_at,
                    recovery_case.created_at,
                    recovery_case.approved_at,
                    recovery_case.issued_at,
                    recovery_case.consumed_at,
                    recovery_case.revoked_at
                  FROM request_engine.identity_recovery_cases AS recovery_case
                 WHERE recovery_case.id = v_replay.case_id;
                RETURN;
            END IF;

            SELECT * INTO v_case
              FROM request_engine.identity_recovery_cases
             WHERE id = p_case_id
             FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Identity recovery case does not exist'
                    USING ERRCODE = 'P0002';
            END IF;
            IF v_case.status <> 'approved' THEN
                RAISE EXCEPTION 'Only an approved recovery case can be issued'
                    USING ERRCODE = '55000';
            END IF;
            IF v_case.revision <> p_expected_revision THEN
                RAISE EXCEPTION 'Identity recovery case revision is stale'
                    USING ERRCODE = '40001';
            END IF;
            IF v_case.approval_expires_at IS NULL
               OR v_case.approval_expires_at <= clock_timestamp() THEN
                RAISE EXCEPTION 'Recovery approval has expired'
                    USING ERRCODE = '55000';
            END IF;

            -- Reuse the reservation for this idempotency key; otherwise reserve
            -- the next generation above every live reservation and the last
            -- committed issuance. The FOR UPDATE case lock serializes allocation.
            SELECT reservation.generation INTO v_reserved
              FROM request_engine.identity_recovery_issuance_reservations AS reservation
             WHERE reservation.case_id = p_case_id
               AND reservation.idempotency_key_digest = p_idempotency_key_digest;
            IF NOT FOUND THEN
                SELECT COALESCE(max(reservation.generation), v_case.issuance_generation) + 1
                  INTO v_reserved
                  FROM request_engine.identity_recovery_issuance_reservations AS reservation
                 WHERE reservation.case_id = p_case_id;
                INSERT INTO request_engine.identity_recovery_issuance_reservations
                    (case_id, generation, idempotency_key_digest)
                VALUES (p_case_id, v_reserved, p_idempotency_key_digest);
            END IF;

            RETURN QUERY SELECT
                false,
                recovery_case.id,
                recovery_case.target_native_identity_id,
                recovery_case.status,
                recovery_case.delivery_status,
                recovery_case.revision,
                v_reserved,
                recovery_case.approval_expires_at,
                recovery_case.proof_expires_at,
                recovery_case.created_at,
                recovery_case.approved_at,
                recovery_case.issued_at,
                recovery_case.consumed_at,
                recovery_case.revoked_at
              FROM request_engine.identity_recovery_cases AS recovery_case
             WHERE recovery_case.id = p_case_id;
        END
        $_$;


ALTER FUNCTION request_platform.prepare_identity_recovery_issue(p_case_id uuid, p_expected_revision bigint, p_idempotency_key_digest text, p_intent_digest text) OWNER TO request_platform_control_definer;

--
-- Name: prepare_platform_secret_mutation(text, text, text, uuid, bigint, integer, text, text); Type: FUNCTION; Schema: request_platform; Owner: request_platform_control_definer
--

CREATE FUNCTION request_platform.prepare_platform_secret_mutation(p_operation_kind text, p_purpose text, p_backend text, p_binding_id uuid, p_expected_binding_revision bigint, p_expected_backend_version integer, p_idempotency_key_digest text, p_intent_digest text) RETURNS TABLE(operation_id uuid, operation_kind text, binding_id uuid, secret_id uuid, purpose text, backend text, expected_binding_revision bigint, expected_backend_version integer, applied_backend_version integer, operation_state text, result_binding_id uuid, result_binding_revision bigint, result_binding_status text)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $_$
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
        $_$;


ALTER FUNCTION request_platform.prepare_platform_secret_mutation(p_operation_kind text, p_purpose text, p_backend text, p_binding_id uuid, p_expected_binding_revision bigint, p_expected_backend_version integer, p_idempotency_key_digest text, p_intent_digest text) OWNER TO request_platform_control_definer;

--
-- Name: principal_is_effective_platform_controller(uuid); Type: FUNCTION; Schema: request_platform; Owner: request_platform_control_definer
--

CREATE FUNCTION request_platform.principal_is_effective_platform_controller(p_principal_id uuid) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
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


ALTER FUNCTION request_platform.principal_is_effective_platform_controller(p_principal_id uuid) OWNER TO request_platform_control_definer;

--
-- Name: principal_is_effective_platform_owner(uuid); Type: FUNCTION; Schema: request_platform; Owner: request_platform_control_definer
--

CREATE FUNCTION request_platform.principal_is_effective_platform_owner(p_principal_id uuid) RETURNS boolean
    LANGUAGE plpgsql STABLE SECURITY DEFINER
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


ALTER FUNCTION request_platform.principal_is_effective_platform_owner(p_principal_id uuid) OWNER TO request_platform_control_definer;

--
-- Name: provision_native_identity(uuid, uuid, text, uuid, text, text, text); Type: FUNCTION; Schema: request_platform; Owner: request_platform_control_definer
--

CREATE FUNCTION request_platform.provision_native_identity(p_authority uuid, p_identity uuid, p_login text, p_credential uuid, p_verifier text, p_key text, p_intent text) RETURNS TABLE(native_identity_id uuid, login_handle text)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $_$
    DECLARE actor_id uuid; actor_revision bigint; retained record; created boolean;
    BEGIN
        PERFORM request_engine.acquire_identity_topology_share();
        IF p_authority IS NULL OR p_identity IS NULL OR p_credential IS NULL
           OR p_login IS NULL OR length(p_login) NOT BETWEEN 1 AND 320
           OR p_key IS NULL OR p_key !~ '^[0-9a-f]{64}$'
           OR p_intent IS NULL OR p_intent !~ '^[0-9a-f]{64}$'
           OR p_verifier IS NULL OR p_verifier NOT LIKE '$argon2id$%' THEN
            RAISE EXCEPTION 'Invalid native provision input' USING ERRCODE='22023';
        END IF;
        BEGIN
            actor_id := NULLIF(current_setting(
                'request_engine.authenticated_principal_id', true),'')::uuid;
            actor_revision := NULLIF(current_setting(
                'request_engine.authority_revision', true),'')::bigint;
        EXCEPTION WHEN invalid_text_representation THEN
            RAISE EXCEPTION 'Malformed platform actor' USING ERRCODE='28000';
        END;
        -- The actor is the shared serialization root of authority withdrawal and
        -- competing administrative retries. Authority is checked before every receipt.
        PERFORM 1 FROM request_engine.principals p WHERE p.id=actor_id
          AND p.principal_plane='platform' AND p.principal_kind='human'
          AND p.active AND p.authority_revision=actor_revision FOR UPDATE;
        IF NOT FOUND OR NOT EXISTS (
            SELECT 1 FROM request_engine.principal_authority_grants g
            WHERE g.principal_id=actor_id AND g.principal_plane='platform'
              AND g.authority_plane='platform' AND g.status='active'
              AND g.capability_key='platform.identity.provision'
        ) THEN
            RAISE EXCEPTION 'Current provision authority required' USING ERRCODE='42501';
        END IF;

        IF coalesce(current_setting('request_engine.authentication_method',true),'')
            <>'native_session'
           OR NOT EXISTS (
            SELECT 1 FROM request_engine.identity_bindings b
            WHERE b.principal_id=actor_id AND b.principal_plane='platform'
              AND b.status='active' AND b.subject_id=
                request_auth.lock_accepted_native_session(NULLIF(current_setting(
                    'request_engine.credential_id',true),'')::uuid,
                    b.identity_authority_id)::text
        ) THEN
            RAISE EXCEPTION 'Current accepted native actor required' USING ERRCODE='42501';
        END IF;
        SELECT r.actor_principal_id,r.idempotency_key_digest,r.intent_digest,r.native_identity_id,r.login_handle INTO retained FROM request_engine.native_identity_provision_receipts r
            WHERE r.actor_principal_id=actor_id AND r.idempotency_key_digest=p_key;
        IF FOUND THEN
            IF retained.intent_digest<>p_intent THEN
                RAISE EXCEPTION 'Conflicting provision intent' USING ERRCODE='23505';
            END IF;
            RETURN QUERY SELECT retained.native_identity_id, retained.login_handle;
            RETURN;
        END IF;
        created := request_auth.create_native_identity(
            p_authority,p_identity,p_login,p_credential,p_verifier);
        IF created IS NULL THEN
            RAISE EXCEPTION 'Native authority unavailable' USING ERRCODE='55000';
        END IF;
        IF NOT created THEN
            RAISE EXCEPTION 'Native login already enrolled' USING ERRCODE='23505';
        END IF;
        INSERT INTO request_engine.native_identity_provision_receipts(
            actor_principal_id,idempotency_key_digest,intent_digest,native_identity_id,
            login_handle,correlation_id)
        VALUES(actor_id,p_key,p_intent,p_identity,p_login,NULLIF(current_setting(
            'request_engine.correlation_id',true),'')::uuid);
        RETURN QUERY SELECT p_identity,p_login;
    END $_$;


ALTER FUNCTION request_platform.provision_native_identity(p_authority uuid, p_identity uuid, p_login text, p_credential uuid, p_verifier text, p_key text, p_intent text) OWNER TO request_platform_control_definer;

--
-- Name: provision_native_organization_root(uuid, text, text, uuid, uuid, uuid, uuid, text); Type: FUNCTION; Schema: request_platform; Owner: request_platform_control_definer
--

CREATE FUNCTION request_platform.provision_native_organization_root(p_organization_id uuid, p_organization_key text, p_display_name text, p_organization_party_id uuid, p_controller_principal_id uuid, p_identity_authority_id uuid, p_native_identity_id uuid, p_provenance_reference text) RETURNS TABLE(organization_id uuid, organization_party_id uuid, controller_principal_id uuid, controller_binding_id uuid)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        DECLARE
            v_creator_id uuid;
            v_expected_revision bigint;
            v_current_revision bigint;
            v_creator_kind text;
            v_can_provision boolean;
            v_binding_id uuid := pg_catalog.gen_random_uuid();
            v_existing record;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
            BEGIN
                v_creator_id := current_setting(
                    'request_engine.authenticated_principal_id', true
                )::uuid;
                v_expected_revision := current_setting(
                    'request_engine.authority_revision', true
                )::bigint;
            EXCEPTION WHEN invalid_text_representation THEN
                RAISE EXCEPTION 'Platform actor provenance is missing or malformed'
                    USING ERRCODE = '28000';
            END;
            IF v_creator_id IS NULL OR v_expected_revision IS NULL THEN
                RAISE EXCEPTION 'Platform actor provenance is required' USING ERRCODE = '28000';
            END IF;
            IF length(btrim(p_organization_key)) = 0
               OR length(btrim(p_display_name)) = 0
               OR length(btrim(p_provenance_reference)) = 0
            THEN
                RAISE EXCEPTION 'Organization root provisioning inputs must be nonblank'
                    USING ERRCODE = '22023';
            END IF;

            SELECT principal.principal_kind, principal.authority_revision
              INTO v_creator_kind, v_current_revision
              FROM request_engine.principals AS principal
             WHERE principal.id = v_creator_id
               AND principal.principal_plane = 'platform'
               AND principal.organization_id IS NULL
               AND principal.active
             FOR UPDATE OF principal;
            IF NOT FOUND OR v_creator_kind <> 'human' THEN
                RAISE EXCEPTION 'Current Platform Principal is not provision-capable'
                    USING ERRCODE = '42501';
            END IF;
            IF v_current_revision <> v_expected_revision THEN
                RAISE EXCEPTION 'Platform authority revision is stale' USING ERRCODE = '40001';
            END IF;
            SELECT EXISTS (
                SELECT 1 FROM request_engine.principal_authority_grants AS grant_row
                 WHERE grant_row.principal_id = v_creator_id
                   AND grant_row.principal_plane = 'platform'
                   AND grant_row.authority_plane = 'platform'
                   AND grant_row.capability_key = 'organization.provision'
                   AND grant_row.status = 'active'
            ) INTO v_can_provision;
            IF NOT v_can_provision THEN
                RAISE EXCEPTION 'Current Platform Principal lacks organization.provision'
                    USING ERRCODE = '42501';
            END IF;

            SELECT root_fact.organization_id,
                   root_fact.organization_party_id,
                   root_fact.controller_principal_id,
                   root_fact.controller_binding_id,
                   root_fact.provisioned_by_principal_id,
                   root_fact.provenance_reference
              INTO v_existing
              FROM request_engine.organization_root_provisioning_facts AS root_fact
             WHERE root_fact.organization_id = p_organization_id;
            IF FOUND THEN
                IF v_existing.organization_party_id <> p_organization_party_id
                   OR v_existing.controller_principal_id <> p_controller_principal_id
                   OR v_existing.provisioned_by_principal_id <> v_creator_id
                   OR v_existing.provenance_reference <> btrim(p_provenance_reference)
                THEN
                    RAISE EXCEPTION 'Organization root replay conflicts with existing root'
                        USING ERRCODE = '23505';
                END IF;
                RETURN QUERY SELECT
                    v_existing.organization_id,
                    v_existing.organization_party_id,
                    v_existing.controller_principal_id,
                    v_existing.controller_binding_id;
                RETURN;
            END IF;

            IF NOT request_auth.lock_credentialed_native_identity(
                p_identity_authority_id,
                p_native_identity_id
            ) THEN
                RAISE EXCEPTION
                    'First tenant controller requires an active credentialed Native identity'
                    USING ERRCODE = '23514';
            END IF;

            INSERT INTO request_engine.organizations (id, organization_key, display_name)
            VALUES (p_organization_id, btrim(p_organization_key), btrim(p_display_name));
            INSERT INTO request_engine.parties (
                id, organization_id, party_kind, display_name
            ) VALUES (
                p_organization_party_id, p_organization_id, 'organization',
                btrim(p_display_name)
            );
            INSERT INTO request_engine.party_identity_revisions (
                organization_id, party_id, revision, change_kind, display_name, active, state
            ) VALUES (
                p_organization_id, p_organization_party_id, 1, 'registered',
                btrim(p_display_name), true,
                pg_catalog.jsonb_build_object(
                    'display_name', btrim(p_display_name),
                    'active', true,
                    'contact_points', '[]'::jsonb,
                    'documents', '[]'::jsonb
                )
            );
            INSERT INTO request_engine.principals (
                id, organization_id, principal_plane, principal_kind, external_subject
            ) VALUES (
                p_controller_principal_id, p_organization_id, 'tenant', 'human',
                'native:' || p_native_identity_id::text
            );
            INSERT INTO request_engine.identity_bindings (
                id, organization_id, principal_id, principal_plane,
                identity_authority_id, subject_id, status
            ) VALUES (
                v_binding_id, p_organization_id, p_controller_principal_id, 'tenant',
                p_identity_authority_id, p_native_identity_id::text, 'active'
            );

            INSERT INTO request_engine.principal_authority_grants (
                organization_id, principal_id, principal_plane, authority_plane,
                capability_key, delegable, granted_by_principal_id,
                provenance_kind, provenance_reference
            )
            SELECT p_organization_id, p_controller_principal_id, 'tenant', 'tenant_control',
                   capability_key, false, v_creator_id, 'provisioning',
                   btrim(p_provenance_reference)
              FROM (VALUES
                  ('staff.invite'),
                  ('staff.manage_membership'),
                  ('staff.manage_authority'),
                  ('agent.provision'),
                  ('agent.manage_authority'),
                  ('agent.suspend'),
                  ('identity.bind')
              ) AS root_control(capability_key);

            INSERT INTO request_engine.representations (
                organization_id, principal_id, represented_party_id, authority_kind, scope_key
            )
            SELECT p_organization_id, p_controller_principal_id, p_organization_party_id,
                   'delegated', scope_key
              FROM (VALUES
                  ('operations.manage_profile'),
                  ('operations.manage_supply'),
                  ('operations.manage_terms'),
                  ('operations.manage_discovery')
              ) AS root_operations(scope_key);

            INSERT INTO request_engine.organization_provisioning_facts (
                organization_id, provisioned_by_principal_id, provenance_reference
            ) VALUES (
                p_organization_id, v_creator_id, btrim(p_provenance_reference)
            );
            INSERT INTO request_engine.organization_root_provisioning_facts (
                organization_id, organization_party_id, controller_principal_id,
                controller_binding_id, provisioned_by_principal_id, provenance_reference
            ) VALUES (
                p_organization_id, p_organization_party_id, p_controller_principal_id,
                v_binding_id, v_creator_id, btrim(p_provenance_reference)
            );

            RETURN QUERY SELECT
                p_organization_id, p_organization_party_id,
                p_controller_principal_id, v_binding_id;
        END
        $$;


ALTER FUNCTION request_platform.provision_native_organization_root(p_organization_id uuid, p_organization_key text, p_display_name text, p_organization_party_id uuid, p_controller_principal_id uuid, p_identity_authority_id uuid, p_native_identity_id uuid, p_provenance_reference text) OWNER TO request_platform_control_definer;

--
-- Name: provision_native_platform_owner(uuid, uuid, uuid, uuid, text, text, text); Type: FUNCTION; Schema: request_platform; Owner: request_platform_control_definer
--

CREATE FUNCTION request_platform.provision_native_platform_owner(p_principal_id uuid, p_binding_id uuid, p_identity_authority_id uuid, p_native_identity_id uuid, p_provenance_reference text, p_idempotency_key_digest text, p_intent_digest text) RETURNS uuid
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $_$
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
             WHERE policy.policy_key = 'platform-owner-v5';
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
        $_$;


ALTER FUNCTION request_platform.provision_native_platform_owner(p_principal_id uuid, p_binding_id uuid, p_identity_authority_id uuid, p_native_identity_id uuid, p_provenance_reference text, p_idempotency_key_digest text, p_intent_digest text) OWNER TO request_platform_control_definer;

--
-- Name: provision_native_recovery_operator(uuid, uuid, uuid, uuid, text); Type: FUNCTION; Schema: request_platform; Owner: request_platform_control_definer
--

CREATE FUNCTION request_platform.provision_native_recovery_operator(p_principal_id uuid, p_binding_id uuid, p_identity_authority_id uuid, p_native_identity_id uuid, p_provenance_reference text) RETURNS uuid
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_creator_id uuid;
    v_creator_revision bigint;
    v_current_revision bigint;
    v_creator_kind text;
    v_creator_active boolean;
BEGIN
    PERFORM request_engine.acquire_identity_topology_share();

    IF p_principal_id IS NULL OR p_binding_id IS NULL
       OR p_identity_authority_id IS NULL OR p_native_identity_id IS NULL
       OR p_provenance_reference IS NULL
       OR length(btrim(p_provenance_reference)) NOT BETWEEN 1 AND 500
    THEN
        RAISE EXCEPTION 'Recovery operator identity and provenance are required'
            USING ERRCODE = '22023';
    END IF;

    BEGIN
        v_creator_id := NULLIF(current_setting(
            'request_engine.authenticated_principal_id', true
        ), '')::uuid;
        v_creator_revision := NULLIF(current_setting(
            'request_engine.authority_revision', true
        ), '')::bigint;
    EXCEPTION WHEN invalid_text_representation THEN
        RAISE EXCEPTION 'Platform actor provenance is malformed'
            USING ERRCODE = '28000';
    END;

    IF v_creator_id IS NULL OR v_creator_revision IS NULL THEN
        RAISE EXCEPTION 'Platform actor provenance is required'
            USING ERRCODE = '28000';
    END IF;

    SELECT principal_kind, active, authority_revision
      INTO v_creator_kind, v_creator_active, v_current_revision
      FROM request_engine.principals
     WHERE id = v_creator_id
       AND principal_plane = 'platform'
     FOR UPDATE;

    IF NOT FOUND OR NOT v_creator_active OR v_creator_kind <> 'human' THEN
        RAISE EXCEPTION 'Recovery operator provisioning requires an active HUMAN controller'
            USING ERRCODE = '42501';
    END IF;
    IF v_current_revision <> v_creator_revision THEN
        RAISE EXCEPTION 'Platform authority revision is stale'
            USING ERRCODE = '40001';
    END IF;
    IF NOT EXISTS (
        SELECT 1
          FROM request_engine.principal_authority_grants AS grant_row
         WHERE grant_row.principal_id = v_creator_id
           AND grant_row.principal_plane = 'platform'
           AND grant_row.authority_plane = 'platform'
           AND grant_row.capability_key = 'platform.recovery_operator.provision'
           AND grant_row.status = 'active'
    ) THEN
        RAISE EXCEPTION 'Platform actor cannot provision bounded Principals'
            USING ERRCODE = '42501';
    END IF;

    -- lock_credentialed_native_identity locks and validates the active Native
    -- authority as well as the credentialed identity under the topology gate.
    IF NOT request_auth.lock_credentialed_native_identity(
        p_identity_authority_id, p_native_identity_id
    ) THEN
        RAISE EXCEPTION 'Active credentialed Native identity is required'
            USING ERRCODE = '23514';
    END IF;

    IF EXISTS (
        SELECT 1 FROM request_engine.principals WHERE id = p_principal_id
    ) OR EXISTS (
        SELECT 1 FROM request_engine.identity_bindings WHERE id = p_binding_id
    ) THEN
        IF EXISTS (
            SELECT 1
              FROM request_engine.principals AS principal
              JOIN request_engine.identity_bindings AS binding
                ON binding.principal_id = principal.id
             WHERE principal.id = p_principal_id
               AND principal.principal_plane = 'platform'
               AND principal.principal_kind = 'human'
               AND principal.external_subject =
                   'native-recovery-operator:' || p_native_identity_id::text
               AND binding.id = p_binding_id
               AND binding.principal_plane = 'platform'
               AND binding.identity_authority_id = p_identity_authority_id
               AND binding.subject_id = p_native_identity_id::text
               AND binding.status = 'active'
               AND (
                   SELECT count(DISTINCT grant_row.capability_key)
                     FROM request_engine.principal_authority_grants AS grant_row
                    WHERE grant_row.principal_id = p_principal_id
                      AND grant_row.principal_plane = 'platform'
                      AND grant_row.authority_plane = 'platform'
                      AND grant_row.status = 'active'
                      AND NOT grant_row.delegable
                      AND grant_row.granted_by_principal_id = v_creator_id
                      AND grant_row.provenance_kind = 'provisioning'
                      AND grant_row.provenance_reference = btrim(p_provenance_reference)
                      AND grant_row.capability_key IN (
                          'platform.identity.read',
                          'platform.identity.recovery_approve'
                      )
               ) = 2
               AND NOT EXISTS (
                   SELECT 1
                     FROM request_engine.principal_authority_grants AS unexpected
                    WHERE unexpected.principal_id = p_principal_id
                      AND unexpected.status = 'active'
                      AND unexpected.capability_key NOT IN (
                          'platform.identity.read',
                          'platform.identity.recovery_approve'
                      )
               )
        ) THEN
            RETURN p_principal_id;
        END IF;
        RAISE EXCEPTION 'Recovery operator provisioning replay conflicts'
            USING ERRCODE = '23505';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM request_engine.identity_bindings
         WHERE identity_authority_id = p_identity_authority_id
           AND subject_id = p_native_identity_id::text
           AND principal_plane = 'platform'
    ) THEN
        RAISE EXCEPTION 'Native identity already has platform binding history'
            USING ERRCODE = '23505';
    END IF;

    INSERT INTO request_engine.principals (
        id, principal_plane, principal_kind, external_subject
    ) VALUES (
        p_principal_id,
        'platform',
        'human',
        'native-recovery-operator:' || p_native_identity_id::text
    );

    INSERT INTO request_engine.identity_bindings (
        id, principal_id, principal_plane, identity_authority_id, subject_id, status
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
        delegable, granted_by_principal_id, provenance_kind, provenance_reference
    )
    SELECT p_principal_id,
           'platform',
           'platform',
           capability_key,
           false,
           v_creator_id,
           'provisioning',
           btrim(p_provenance_reference)
      FROM (VALUES
          ('platform.identity.read'),
          ('platform.identity.recovery_approve')
      ) AS bounded_grant(capability_key);

    RETURN p_principal_id;
END
$$;


ALTER FUNCTION request_platform.provision_native_recovery_operator(p_principal_id uuid, p_binding_id uuid, p_identity_authority_id uuid, p_native_identity_id uuid, p_provenance_reference text) OWNER TO request_platform_control_definer;

--
-- Name: provision_native_tenant_provisioner(uuid, uuid, uuid, uuid, text); Type: FUNCTION; Schema: request_platform; Owner: request_platform_control_definer
--

CREATE FUNCTION request_platform.provision_native_tenant_provisioner(p_principal_id uuid, p_binding_id uuid, p_identity_authority_id uuid, p_native_identity_id uuid, p_provenance_reference text) RETURNS uuid
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        DECLARE
            v_creator_id uuid;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
            IF p_principal_id IS NULL OR p_binding_id IS NULL
               OR p_identity_authority_id IS NULL OR p_native_identity_id IS NULL
               OR p_provenance_reference IS NULL
               OR length(btrim(p_provenance_reference)) NOT BETWEEN 1 AND 500 THEN
                RAISE EXCEPTION 'Native provisioner identity and provenance are required'
                    USING ERRCODE = '22023';
            END IF;
            BEGIN
                v_creator_id := NULLIF(current_setting(
                    'request_engine.authenticated_principal_id', true
                ), '')::uuid;
            EXCEPTION WHEN invalid_text_representation THEN
                RAISE EXCEPTION 'Platform actor provenance is malformed' USING ERRCODE = '28000';
            END;
            IF v_creator_id IS NULL THEN
                RAISE EXCEPTION 'Platform actor provenance is required' USING ERRCODE = '28000';
            END IF;

            -- Keep the creator lock outside the exception subtransaction so a
            -- replay cannot race a committed revocation of the creator's grants.
            PERFORM 1 FROM request_engine.principals
             WHERE id = v_creator_id AND principal_plane = 'platform'
             FOR UPDATE;
            BEGIN
                -- This existing command remains the single authority/ceiling
                -- gate, including on replay before it reaches a unique conflict.
                PERFORM request_platform.provision_tenant_provisioner(
                    p_principal_id,
                    'native:' || p_identity_authority_id::text || ':' || p_native_identity_id::text,
                    btrim(p_provenance_reference)
                );
                IF NOT request_auth.lock_credentialed_native_identity(
                    p_identity_authority_id, p_native_identity_id
                ) THEN
                    RAISE EXCEPTION 'Active credentialed Native identity is required'
                        USING ERRCODE = '23514';
                END IF;
                IF EXISTS (
                    SELECT 1 FROM request_engine.identity_bindings
                     WHERE identity_authority_id = p_identity_authority_id
                       AND subject_id = p_native_identity_id::text
                       AND principal_plane = 'platform' AND organization_id IS NULL
                ) THEN
                    RAISE EXCEPTION 'Native identity already has platform binding history'
                        USING ERRCODE = '23505';
                END IF;
                INSERT INTO request_engine.identity_bindings (
                    id, principal_id, principal_plane, identity_authority_id, subject_id, status
                ) VALUES (
                    p_binding_id, p_principal_id, 'platform', p_identity_authority_id,
                    p_native_identity_id::text, 'active'
                );
                RETURN p_principal_id;
            EXCEPTION WHEN unique_violation THEN
                -- The failed attempt has rolled back all of its writes. Compare
                -- every immutable input/provenance field; never activate/regrant.
                IF EXISTS (
                    SELECT 1 FROM request_engine.identity_bindings b
                    JOIN request_engine.principals p ON p.id = b.principal_id
                    JOIN request_engine.principal_authority_grants g ON g.principal_id = p.id
                    WHERE b.id = p_binding_id AND b.principal_id = p_principal_id
                      AND b.identity_authority_id = p_identity_authority_id
                      AND b.subject_id = p_native_identity_id::text
                      AND b.principal_plane = 'platform' AND b.organization_id IS NULL
                      AND p.principal_plane = 'platform' AND p.organization_id IS NULL
                      AND p.principal_kind = 'human'
                      AND g.principal_plane = 'platform' AND g.authority_plane = 'platform'
                      AND g.capability_key = 'organization.provision' AND NOT g.delegable
                      AND g.granted_by_principal_id = v_creator_id
                      AND g.provenance_kind = 'provisioning'
                      AND g.provenance_reference = btrim(p_provenance_reference)
                ) THEN
                    RETURN p_principal_id;
                END IF;
                RAISE;
            END;
        END $$;


ALTER FUNCTION request_platform.provision_native_tenant_provisioner(p_principal_id uuid, p_binding_id uuid, p_identity_authority_id uuid, p_native_identity_id uuid, p_provenance_reference text) OWNER TO request_platform_control_definer;

--
-- Name: provision_tenant_provisioner(uuid, text, text); Type: FUNCTION; Schema: request_platform; Owner: request_platform_control_definer
--

CREATE FUNCTION request_platform.provision_tenant_provisioner(p_new_principal_id uuid, p_external_subject text, p_provenance_reference text) RETURNS uuid
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        DECLARE
            v_creator_id uuid;
            v_expected_revision bigint;
            v_current_revision bigint;
            v_creator_kind text;
            v_has_command boolean;
            v_can_delegate_org boolean;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
            BEGIN
                v_creator_id := current_setting(
                    'request_engine.authenticated_principal_id', true
                )::uuid;
                v_expected_revision := current_setting(
                    'request_engine.authority_revision', true
                )::bigint;
            EXCEPTION WHEN invalid_text_representation THEN
                RAISE EXCEPTION 'Platform actor provenance is missing or malformed'
                    USING ERRCODE = '28000';
            END;
            IF v_creator_id IS NULL OR v_expected_revision IS NULL THEN
                RAISE EXCEPTION 'Platform actor provenance is required' USING ERRCODE = '28000';
            END IF;
            IF length(btrim(p_external_subject)) = 0
               OR length(btrim(p_provenance_reference)) = 0
            THEN
                RAISE EXCEPTION 'Provisioning subject and provenance must be nonblank'
                    USING ERRCODE = '22023';
            END IF;

            SELECT principal_kind, authority_revision
              INTO v_creator_kind, v_current_revision
              FROM request_engine.principals
             WHERE id = v_creator_id
               AND principal_plane = 'platform'
               AND organization_id IS NULL
               AND active
             FOR UPDATE;
            IF NOT FOUND OR v_creator_kind <> 'human' THEN
                RAISE EXCEPTION 'Current Platform Principal is not provision-capable'
                    USING ERRCODE = '42501';
            END IF;
            IF v_current_revision <> v_expected_revision THEN
                RAISE EXCEPTION 'Platform authority revision is stale' USING ERRCODE = '40001';
            END IF;

            SELECT EXISTS (
                       SELECT 1 FROM request_engine.principal_authority_grants
                        WHERE principal_id = v_creator_id
                          AND principal_plane = 'platform'
                          AND authority_plane = 'platform'
                          AND capability_key = 'platform.tenant_provisioner.provision'
                          AND status = 'active'
                   ),
                   EXISTS (
                       SELECT 1 FROM request_engine.principal_authority_grants
                        WHERE principal_id = v_creator_id
                          AND principal_plane = 'platform'
                          AND authority_plane = 'platform'
                          AND capability_key = 'organization.provision'
                          AND delegable
                          AND status = 'active'
                   )
              INTO v_has_command, v_can_delegate_org;
            IF NOT v_has_command OR NOT v_can_delegate_org THEN
                RAISE EXCEPTION 'Current Platform Principal lacks bounded provisioning authority'
                    USING ERRCODE = '42501';
            END IF;

            INSERT INTO request_engine.principals (
                id, principal_plane, principal_kind, external_subject
            ) VALUES (
                p_new_principal_id, 'platform', 'human', btrim(p_external_subject)
            );
            INSERT INTO request_engine.principal_authority_grants (
                principal_id,
                principal_plane,
                authority_plane,
                capability_key,
                delegable,
                granted_by_principal_id,
                provenance_kind,
                provenance_reference
            ) VALUES (
                p_new_principal_id,
                'platform',
                'platform',
                'organization.provision',
                false,
                v_creator_id,
                'provisioning',
                btrim(p_provenance_reference)
            );
            RETURN p_new_principal_id;
        END
        $$;


ALTER FUNCTION request_platform.provision_tenant_provisioner(p_new_principal_id uuid, p_external_subject text, p_provenance_reference text) OWNER TO request_platform_control_definer;

--
-- Name: read_active_appointment_option_signing_keyring(); Type: FUNCTION; Schema: request_platform; Owner: request_platform_definer
--

CREATE FUNCTION request_platform.read_active_appointment_option_signing_keyring() RETURNS TABLE(configuration_revision bigint, secret_binding_revision bigint, secret_id uuid, secret_backend_version integer)
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
            SELECT
                config.revision,
                binding.revision,
                binding.secret_id,
                binding.backend_version
              FROM request_engine.platform_configuration_revisions AS config
              JOIN request_engine.platform_secret_bindings AS binding
                ON binding.id = config.secret_binding_id
             WHERE config.configuration_kind = 'security.appointment_option_signing'
               AND config.provider_kind = 'hmac-sha256-keyring'
               AND config.state = 'active'
               AND config.configuration = '{}'::jsonb
               AND binding.purpose = 'security.appointment_option_signing'
               AND binding.backend = 'openbao'
               AND binding.status = 'active'
        $$;


ALTER FUNCTION request_platform.read_active_appointment_option_signing_keyring() OWNER TO request_platform_definer;

--
-- Name: read_active_platform_runtime_configuration(text); Type: FUNCTION; Schema: request_platform; Owner: request_platform_definer
--

CREATE FUNCTION request_platform.read_active_platform_runtime_configuration(p_configuration_kind text) RETURNS TABLE(configuration_revision_id uuid, configuration_kind text, provider_kind text, revision bigint, configuration jsonb, secret_binding_id uuid, secret_binding_revision bigint, secret_id uuid, secret_purpose text, secret_backend text, secret_backend_version integer, secret_status text)
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $_$
            SELECT
                config.id,
                config.configuration_kind,
                config.provider_kind,
                config.revision,
                config.configuration,
                config.secret_binding_id,
                binding.revision,
                binding.secret_id,
                binding.purpose,
                binding.backend,
                binding.backend_version,
                binding.status
              FROM request_engine.platform_configuration_revisions AS config
              LEFT JOIN request_engine.platform_secret_bindings AS binding
                ON binding.id = config.secret_binding_id
             WHERE config.configuration_kind = p_configuration_kind
               AND config.state = 'active'
               AND p_configuration_kind ~ '^[a-z][a-z0-9_.-]{1,79}$'
        $_$;


ALTER FUNCTION request_platform.read_active_platform_runtime_configuration(p_configuration_kind text) OWNER TO request_platform_definer;

--
-- Name: read_claim_readiness(uuid); Type: FUNCTION; Schema: request_platform; Owner: request_platform_control_definer
--

CREATE FUNCTION request_platform.read_claim_readiness(p_setup_session_id uuid) RETURNS TABLE(setup_status text, setup_usable boolean, instance_state text, has_identity boolean, verified_webauthn_count integer, has_recovery_codes boolean, policy_key text)
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
            SELECT session.status,
                   (session.status = 'pending'
                    AND session.expires_at > clock_timestamp()
                    AND instance.state = 'unclaimed'),
                   instance.state,
                   EXISTS (
                       SELECT 1 FROM request_engine.setup_pending_identity AS identity
                        WHERE identity.setup_session_id = session.id
                          AND identity.status = 'pending'
                   ),
                   (
                       SELECT count(*)::integer
                         FROM request_engine.setup_pending_webauthn_credential AS credential
                        WHERE credential.setup_session_id = session.id
                          AND credential.status = 'pending'
                          AND credential.user_verified
                   ),
                   EXISTS (
                       SELECT 1 FROM request_engine.recovery_code_sets AS code_set
                        WHERE code_set.setup_session_id = session.id
                          AND code_set.status = 'active'
                   ),
                   'platform-owner-v1'
              FROM request_engine.setup_sessions AS session
              JOIN request_engine.platform_instance AS instance
                ON instance.id = session.instance_id
             WHERE session.id = p_setup_session_id
        $$;


ALTER FUNCTION request_platform.read_claim_readiness(p_setup_session_id uuid) OWNER TO request_platform_control_definer;

--
-- Name: read_identity_recovery_cases(uuid, uuid, integer); Type: FUNCTION; Schema: request_platform; Owner: request_platform_definer
--

CREATE FUNCTION request_platform.read_identity_recovery_cases(p_case_id uuid, p_after uuid, p_limit integer) RETURNS TABLE(case_id uuid, target_native_identity_id uuid, status text, delivery_status text, revision bigint, issuance_generation integer, approval_expires_at timestamp with time zone, proof_expires_at timestamp with time zone, created_at timestamp with time zone, approved_at timestamp with time zone, issued_at timestamp with time zone, consumed_at timestamp with time zone, revoked_at timestamp with time zone)
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        BEGIN
            IF p_limit IS NULL OR p_limit < 1 OR p_limit > 100 THEN
                RAISE EXCEPTION 'Identity recovery case page limit must be between 1 and 100'
                    USING ERRCODE = '22023';
            END IF;
            RETURN QUERY SELECT

            recovery_case.id,
            recovery_case.target_native_identity_id,
            recovery_case.status,
            recovery_case.delivery_status,
            recovery_case.revision,
            recovery_case.issuance_generation,
            recovery_case.approval_expires_at,
            recovery_case.proof_expires_at,
            recovery_case.created_at,
            recovery_case.approved_at,
            recovery_case.issued_at,
            recovery_case.consumed_at,
            recovery_case.revoked_at
              FROM request_engine.identity_recovery_cases AS recovery_case
             WHERE (p_case_id IS NULL OR recovery_case.id = p_case_id)
               AND (p_after IS NULL OR recovery_case.id > p_after)
             ORDER BY recovery_case.id
             LIMIT p_limit;
        END
        $$;


ALTER FUNCTION request_platform.read_identity_recovery_cases(p_case_id uuid, p_after uuid, p_limit integer) OWNER TO request_platform_definer;

--
-- Name: read_installation_claim(text, text); Type: FUNCTION; Schema: request_platform; Owner: request_platform_control_definer
--

CREATE FUNCTION request_platform.read_installation_claim(p_idempotency_key_digest text, p_intent_digest text) RETURNS TABLE(instance_id uuid, owner_principal_id uuid, native_identity_id uuid, setup_session_id uuid, policy_key text, claim_provenance text, intent_digest text, claimed_at timestamp with time zone)
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
            SELECT fact.instance_id,
                   fact.owner_principal_id,
                   fact.native_identity_id,
                   fact.setup_session_id,
                   fact.policy_key,
                   fact.claim_provenance,
                   fact.intent_digest,
                   fact.created_at
              FROM request_engine.platform_installation_claim_facts AS fact
             WHERE fact.idempotency_key_digest = p_idempotency_key_digest
               AND fact.intent_digest = p_intent_digest
        $$;


ALTER FUNCTION request_platform.read_installation_claim(p_idempotency_key_digest text, p_intent_digest text) OWNER TO request_platform_control_definer;

--
-- Name: read_installation_claim_intent_digest(text); Type: FUNCTION; Schema: request_platform; Owner: request_platform_control_definer
--

CREATE FUNCTION request_platform.read_installation_claim_intent_digest(p_idempotency_key_digest text) RETURNS text
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
            SELECT fact.intent_digest
              FROM request_engine.platform_installation_claim_facts AS fact
             WHERE fact.idempotency_key_digest = p_idempotency_key_digest
        $$;


ALTER FUNCTION request_platform.read_installation_claim_intent_digest(p_idempotency_key_digest text) OWNER TO request_platform_control_definer;

--
-- Name: read_native_identities(uuid, uuid, integer); Type: FUNCTION; Schema: request_platform; Owner: request_platform_definer
--

CREATE FUNCTION request_platform.read_native_identities(p_identity_id uuid, p_after uuid, p_limit integer) RETURNS TABLE(native_identity_id uuid, identity_authority_id uuid, status text, revision bigint, created_at timestamp with time zone, disabled_at timestamp with time zone)
    LANGUAGE plpgsql STABLE SECURITY DEFINER
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


ALTER FUNCTION request_platform.read_native_identities(p_identity_id uuid, p_after uuid, p_limit integer) OWNER TO request_platform_definer;

--
-- Name: read_native_identity_profiles(uuid, uuid, integer); Type: FUNCTION; Schema: request_platform; Owner: request_platform_definer
--

CREATE FUNCTION request_platform.read_native_identity_profiles(p_identity_id uuid, p_after uuid, p_limit integer) RETURNS TABLE(native_identity_id uuid, identity_authority_id uuid, status text, revision bigint, created_at timestamp with time zone, disabled_at timestamp with time zone, login_handle text)
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
            SELECT page.native_identity_id, page.identity_authority_id,
                   page.status, page.revision, page.created_at, page.disabled_at,
                   identity.login_handle
              FROM request_platform.read_native_identities(
                  p_identity_id, p_after, p_limit
              ) AS page
              JOIN request_engine.native_identities AS identity
                ON identity.id = page.native_identity_id
             ORDER BY page.native_identity_id
        $$;


ALTER FUNCTION request_platform.read_native_identity_profiles(p_identity_id uuid, p_after uuid, p_limit integer) OWNER TO request_platform_definer;

--
-- Name: read_platform_configuration_revisions(text); Type: FUNCTION; Schema: request_platform; Owner: request_platform_definer
--

CREATE FUNCTION request_platform.read_platform_configuration_revisions(p_configuration_kind text) RETURNS TABLE(configuration_revision_id uuid, configuration_kind text, provider_kind text, revision bigint, configuration jsonb, secret_binding_id uuid, state text, created_by_principal_id uuid, created_at timestamp with time zone, validated_at timestamp with time zone, activated_at timestamp with time zone, disabled_at timestamp with time zone)
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $_$
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
        $_$;


ALTER FUNCTION request_platform.read_platform_configuration_revisions(p_configuration_kind text) OWNER TO request_platform_definer;

--
-- Name: read_platform_instance(); Type: FUNCTION; Schema: request_platform; Owner: request_platform_control_definer
--

CREATE FUNCTION request_platform.read_platform_instance() RETURNS TABLE(id uuid, state text, revision bigint, built_in_native_authority_id uuid, built_in_workload_authority_id uuid, claimed_at timestamp with time zone, initial_owner_principal_id uuid, claim_provenance text)
    LANGUAGE sql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
    SELECT instance.id,
           instance.state,
           instance.revision,
           instance.built_in_native_authority_id,
           instance.built_in_workload_authority_id,
           instance.claimed_at,
           instance.initial_owner_principal_id,
           instance.claim_provenance
      FROM request_engine.platform_instance AS instance
     WHERE instance.singleton_key = 1;
$$;


ALTER FUNCTION request_platform.read_platform_instance() OWNER TO request_platform_control_definer;

--
-- Name: read_platform_organizations(uuid, uuid, integer); Type: FUNCTION; Schema: request_platform; Owner: request_platform_definer
--

CREATE FUNCTION request_platform.read_platform_organizations(p_organization_id uuid, p_after uuid, p_limit integer) RETURNS TABLE(organization_id uuid, organization_key text, display_name text, operational_status text, default_timezone text, default_locale text, default_currency text, created_at timestamp with time zone, updated_at timestamp with time zone)
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
BEGIN
    IF p_limit IS NULL OR p_limit < 1 OR p_limit > 100 THEN
        RAISE EXCEPTION 'Organization page limit must be between 1 and 100'
            USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    SELECT organization.id,
           organization.organization_key,
           organization.display_name,
           organization.operational_status,
           organization.default_timezone,
           organization.default_locale,
           organization.default_currency,
           organization.created_at,
           organization.updated_at
      FROM request_engine.organizations AS organization
     WHERE (p_organization_id IS NULL OR organization.id = p_organization_id)
       AND (p_after IS NULL OR organization.id > p_after)
     ORDER BY organization.id
     LIMIT p_limit;
END
$$;


ALTER FUNCTION request_platform.read_platform_organizations(p_organization_id uuid, p_after uuid, p_limit integer) OWNER TO request_platform_definer;

--
-- Name: read_platform_owner_invitations(uuid, uuid, integer); Type: FUNCTION; Schema: request_platform; Owner: request_platform_control_definer
--

CREATE FUNCTION request_platform.read_platform_owner_invitations(p_invitation_id uuid, p_after uuid, p_limit integer) RETURNS TABLE(invitation_id uuid, status text, revision bigint, native_identity_id uuid, created_at timestamp with time zone, expires_at timestamp with time zone, enrolled_at timestamp with time zone, consumed_at timestamp with time zone, revoked_at timestamp with time zone, expired boolean)
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
    BEGIN
        PERFORM request_platform.assert_owner_read_actor();
        IF p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 100 THEN
            RAISE EXCEPTION 'Page limit must be between 1 and 100' USING ERRCODE='22023';
        END IF;
        RETURN QUERY SELECT i.id, i.status, i.revision, i.native_identity_id,
            i.created_at, i.expires_at, i.enrolled_at, i.consumed_at, i.revoked_at,
            i.expires_at<=statement_timestamp()
        FROM request_engine.platform_owner_invitations i
        WHERE (p_invitation_id IS NULL OR i.id=p_invitation_id)
          AND (p_after IS NULL OR i.id>p_after)
        ORDER BY i.id LIMIT CASE WHEN p_invitation_id IS NULL THEN p_limit+1 ELSE 1 END;
    END $$;


ALTER FUNCTION request_platform.read_platform_owner_invitations(p_invitation_id uuid, p_after uuid, p_limit integer) OWNER TO request_platform_control_definer;

--
-- Name: read_platform_owners(uuid, uuid, integer); Type: FUNCTION; Schema: request_platform; Owner: request_platform_control_definer
--

CREATE FUNCTION request_platform.read_platform_owners(p_principal_id uuid, p_after uuid, p_limit integer) RETURNS TABLE(principal_id uuid, active boolean, authority_revision bigint, binding_id uuid, binding_status text, capabilities text[])
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
    BEGIN
        PERFORM request_platform.assert_owner_read_actor();
        IF p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 100 THEN
            RAISE EXCEPTION 'Page limit must be between 1 and 100' USING ERRCODE='22023';
        END IF;
        RETURN QUERY
        SELECT p.id, p.active, p.authority_revision, b.id, b.status,
            ARRAY(SELECT g.capability_key FROM request_engine.principal_authority_grants g
                  WHERE g.principal_id=p.id AND g.principal_plane='platform'
                    AND g.authority_plane='platform' AND g.status='active'
                  ORDER BY g.capability_key)
        FROM request_engine.principals p
        LEFT JOIN LATERAL (
            SELECT binding.id, binding.status FROM request_engine.identity_bindings binding
            WHERE binding.principal_id=p.id AND binding.principal_plane='platform'
            ORDER BY (binding.status='active') DESC, (binding.status='suspended') DESC,
                     binding.id LIMIT 1
        ) b ON true
        WHERE p.principal_plane='platform' AND p.principal_kind='human'
          AND (p_principal_id IS NULL OR p.id=p_principal_id)
          AND (p_after IS NULL OR p.id>p_after)
          AND EXISTS (
            SELECT 1 FROM request_engine.principal_authority_grants historical
            WHERE historical.principal_id=p.id AND historical.principal_plane='platform'
              AND historical.authority_plane='platform'
              AND historical.capability_key='platform.owner.manage_lifecycle'
          )
        ORDER BY p.id LIMIT CASE WHEN p_principal_id IS NULL THEN p_limit+1 ELSE 1 END;
    END $$;


ALTER FUNCTION request_platform.read_platform_owners(p_principal_id uuid, p_after uuid, p_limit integer) OWNER TO request_platform_control_definer;

--
-- Name: read_platform_provider_candidate(text, bigint, text); Type: FUNCTION; Schema: request_platform; Owner: request_platform_control_definer
--

CREATE FUNCTION request_platform.read_platform_provider_candidate(p_configuration_kind text, p_revision bigint, p_capability_key text) RETURNS TABLE(configuration_revision_id uuid, configuration_kind text, provider_kind text, revision bigint, configuration jsonb, secret_binding_id uuid, state text, created_by_principal_id uuid, created_at timestamp with time zone, validated_at timestamp with time zone, activated_at timestamp with time zone, disabled_at timestamp with time zone)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $_$
        DECLARE
            v_ignore_actor uuid;
            v_ignore_method text;
            v_ignore_correlation uuid;
        BEGIN
            IF p_configuration_kind !~ '^[a-z][a-z0-9_.-]{1,79}$'
               OR p_revision IS NULL OR p_revision < 1
               OR p_capability_key NOT IN (
                   'platform.configuration.validate',
                   'platform.provider.test'
               )
            THEN
                RAISE EXCEPTION 'Platform provider candidate input is invalid'
                    USING ERRCODE = '22023';
            END IF;

            SELECT actor_id, actor_method, correlation_id
              INTO v_ignore_actor, v_ignore_method, v_ignore_correlation
              FROM request_platform.assert_platform_configuration_actor(
                  p_capability_key
              );

            RETURN QUERY
            SELECT
                r.id,
                r.configuration_kind,
                r.provider_kind,
                r.revision,
                r.configuration,
                r.secret_binding_id,
                r.state,
                r.created_by_principal_id,
                r.created_at,
                r.validated_at,
                r.activated_at,
                r.disabled_at
              FROM request_engine.platform_configuration_revisions AS r
             WHERE r.configuration_kind = p_configuration_kind
               AND r.revision = p_revision;

            IF NOT FOUND THEN
                RAISE EXCEPTION 'Platform configuration revision does not exist'
                    USING ERRCODE = 'P0002';
            END IF;
        END
        $_$;


ALTER FUNCTION request_platform.read_platform_provider_candidate(p_configuration_kind text, p_revision bigint, p_capability_key text) OWNER TO request_platform_control_definer;

--
-- Name: read_platform_provisioners(uuid, uuid, integer); Type: FUNCTION; Schema: request_platform; Owner: request_platform_definer
--

CREATE FUNCTION request_platform.read_platform_provisioners(p_principal_id uuid, p_after uuid, p_limit integer) RETURNS TABLE(principal_id uuid, principal_kind text, active boolean, authority_revision bigint, binding_id uuid, binding_status text, identity_authority_id uuid, binding_subject_id text, capabilities text[], provenance_reference text, granted_at timestamp with time zone)
    LANGUAGE plpgsql STABLE SECURITY DEFINER
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


ALTER FUNCTION request_platform.read_platform_provisioners(p_principal_id uuid, p_after uuid, p_limit integer) OWNER TO request_platform_definer;

--
-- Name: read_platform_readiness(); Type: FUNCTION; Schema: request_platform; Owner: request_platform_definer
--

CREATE FUNCTION request_platform.read_platform_readiness() RETURNS TABLE(managed_smtp_source text, smtp_active_revision bigint, smtp_last_validated_at timestamp with time zone, smtp_last_provider_test_outcome text, smtp_last_provider_test_at timestamp with time zone, smtp_secret_configured boolean, oidc text)
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        BEGIN
            PERFORM 1
              FROM request_platform.assert_platform_configuration_actor(
                  'platform.readiness.read'
              );

            RETURN QUERY
            WITH active_smtp AS (
                SELECT
                    config.id,
                    config.revision,
                    config.validated_at,
                    config.secret_binding_id
                FROM request_engine.platform_configuration_revisions AS config
                WHERE config.configuration_kind = 'email.delivery'
                  AND config.provider_kind = 'smtp'
                  AND config.state = 'active'
                LIMIT 1
            ),
            active_oidc AS (
                SELECT
                    config.revision,
                    config.configuration ->> 'issuer' AS issuer,
                    config.configuration ->> 'jwks_uri' AS jwks_uri,
                    config.configuration ->> 'audience' AS audience
                FROM request_engine.platform_configuration_revisions AS config
                WHERE config.configuration_kind = 'identity.oidc'
                  AND config.provider_kind = 'oidc'
                  AND config.state = 'active'
                LIMIT 1
            ),
            latest_test AS (
                SELECT
                    fact.detail ->> 'outcome' AS outcome,
                    fact.created_at
                FROM request_engine.platform_configuration_facts AS fact
                JOIN active_smtp AS active
                  ON active.id = fact.configuration_revision_id
                WHERE fact.event_kind = 'provider_tested'
                ORDER BY fact.created_at DESC
                LIMIT 1
            )
            SELECT
                CASE WHEN active.id IS NULL THEN 'none' ELSE 'managed' END,
                active.revision,
                active.validated_at,
                latest.outcome,
                latest.created_at,
                active.secret_binding_id IS NOT NULL,
                CASE
                    WHEN oidc.revision IS NULL THEN 'unconfigured'
                    WHEN request_platform.managed_oidc_projection_matches(
                        oidc.issuer,
                        oidc.jwks_uri,
                        oidc.audience,
                        oidc.revision
                    ) THEN 'managed'
                    ELSE 'degraded'
                END
            FROM (SELECT 1) AS singleton
            LEFT JOIN active_smtp AS active ON true
            LEFT JOIN active_oidc AS oidc ON true
            LEFT JOIN latest_test AS latest ON true;
        END
        $$;


ALTER FUNCTION request_platform.read_platform_readiness() OWNER TO request_platform_definer;

--
-- Name: read_platform_runtime_configuration_revision(text, bigint); Type: FUNCTION; Schema: request_platform; Owner: request_platform_definer
--

CREATE FUNCTION request_platform.read_platform_runtime_configuration_revision(p_configuration_kind text, p_revision bigint) RETURNS TABLE(configuration_revision_id uuid, configuration_kind text, provider_kind text, revision bigint, configuration jsonb, secret_binding_id uuid, secret_binding_revision bigint, secret_id uuid, secret_purpose text, secret_backend text, secret_backend_version integer, secret_status text)
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $_$
            SELECT
                config.id,
                config.configuration_kind,
                config.provider_kind,
                config.revision,
                config.configuration,
                config.secret_binding_id,
                binding.revision,
                binding.secret_id,
                binding.purpose,
                binding.backend,
                binding.backend_version,
                binding.status
              FROM request_engine.platform_configuration_revisions AS config
              LEFT JOIN request_engine.platform_secret_bindings AS binding
                ON binding.id = config.secret_binding_id
             WHERE config.configuration_kind = p_configuration_kind
               AND config.revision = p_revision
               AND config.state IN ('active', 'superseded')
               AND p_configuration_kind ~ '^[a-z][a-z0-9_.-]{1,79}$'
               AND p_revision > 0
        $_$;


ALTER FUNCTION request_platform.read_platform_runtime_configuration_revision(p_configuration_kind text, p_revision bigint) OWNER TO request_platform_definer;

--
-- Name: read_platform_secret_binding(uuid); Type: FUNCTION; Schema: request_platform; Owner: request_platform_definer
--

CREATE FUNCTION request_platform.read_platform_secret_binding(p_binding_id uuid) RETURNS TABLE(binding_id uuid, purpose text, backend text, backend_version integer, status text, revision bigint, created_at timestamp with time zone, rotated_at timestamp with time zone, revoked_at timestamp with time zone)
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
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
        $$;


ALTER FUNCTION request_platform.read_platform_secret_binding(p_binding_id uuid) OWNER TO request_platform_definer;

--
-- Name: read_principal_authority(uuid); Type: FUNCTION; Schema: request_platform; Owner: request_platform_definer
--

CREATE FUNCTION request_platform.read_principal_authority(p_principal_id uuid) RETURNS TABLE(principal_kind text, active boolean, authority_revision bigint, capability_key text, delegable boolean)
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
            SELECT p.principal_kind,
                   p.active,
                   p.authority_revision,
                   g.capability_key,
                   g.delegable
              FROM request_engine.principals AS p
              LEFT JOIN request_engine.principal_authority_grants AS g
                ON g.principal_id = p.id
               AND g.principal_plane = 'platform'
               AND g.authority_plane = 'platform'
               AND g.status = 'active'
             WHERE p.id = p_principal_id
               AND p.principal_plane = 'platform'
             ORDER BY g.capability_key
        $$;


ALTER FUNCTION request_platform.read_principal_authority(p_principal_id uuid) OWNER TO request_platform_definer;

--
-- Name: read_setup_pending_identity(uuid); Type: FUNCTION; Schema: request_platform; Owner: request_platform_control_definer
--

CREATE FUNCTION request_platform.read_setup_pending_identity(p_setup_session_id uuid) RETURNS TABLE(native_identity_id uuid, login_handle text, status text)
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
            SELECT identity.id, identity.login_handle, identity.status
              FROM request_engine.setup_pending_identity AS identity
             WHERE identity.setup_session_id = p_setup_session_id
        $$;


ALTER FUNCTION request_platform.read_setup_pending_identity(p_setup_session_id uuid) OWNER TO request_platform_control_definer;

--
-- Name: read_setup_session(bytea); Type: FUNCTION; Schema: request_platform; Owner: request_platform_control_definer
--

CREATE FUNCTION request_platform.read_setup_session(p_token_digest bytea) RETURNS TABLE(id uuid, status text, mode text, expires_at timestamp with time zone, consumed_at timestamp with time zone, instance_state text, is_usable boolean)
    LANGUAGE sql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
    SELECT session.id,
           session.status,
           session.mode,
           session.expires_at,
           session.consumed_at,
           instance.state,
           (
               session.status = 'pending'
               AND session.expires_at > clock_timestamp()
               AND instance.state = 'unclaimed'
           )
      FROM request_engine.setup_sessions AS session
      JOIN request_engine.platform_instance AS instance
        ON instance.singleton_key = 1
     WHERE session.token_digest = p_token_digest;
$$;


ALTER FUNCTION request_platform.read_setup_session(p_token_digest bytea) OWNER TO request_platform_control_definer;

--
-- Name: record_platform_provider_test(text, bigint, bigint, integer, text, text, text, text); Type: FUNCTION; Schema: request_platform; Owner: request_platform_control_definer
--

CREATE FUNCTION request_platform.record_platform_provider_test(p_configuration_kind text, p_revision bigint, p_expected_binding_revision bigint, p_expected_backend_version integer, p_outcome text, p_detail_code text, p_idempotency_key_digest text, p_intent_digest text) RETURNS uuid
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $_$
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
        $_$;


ALTER FUNCTION request_platform.record_platform_provider_test(p_configuration_kind text, p_revision bigint, p_expected_binding_revision bigint, p_expected_backend_version integer, p_outcome text, p_detail_code text, p_idempotency_key_digest text, p_intent_digest text) OWNER TO request_platform_control_definer;

--
-- Name: record_platform_secret_binding(text, text, uuid, integer, text, text); Type: FUNCTION; Schema: request_platform; Owner: request_platform_control_definer
--

CREATE FUNCTION request_platform.record_platform_secret_binding(p_purpose text, p_backend text, p_secret_id uuid, p_backend_version integer, p_idempotency_key_digest text, p_intent_digest text) RETURNS TABLE(binding_id uuid, revision bigint, backend_version integer, status text)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $_$
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
                    'p7/idempotency/'
                    || v_actor_id::text
                    || '/platform.secret.write/'
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
        $_$;


ALTER FUNCTION request_platform.record_platform_secret_binding(p_purpose text, p_backend text, p_secret_id uuid, p_backend_version integer, p_idempotency_key_digest text, p_intent_digest text) OWNER TO request_platform_control_definer;

--
-- Name: renew_identity_recovery_delivery_ticket_lease(uuid, uuid, integer); Type: FUNCTION; Schema: request_platform; Owner: request_platform_control_definer
--

CREATE FUNCTION request_platform.renew_identity_recovery_delivery_ticket_lease(p_ticket_id uuid, p_claim_token uuid, p_extension_seconds integer) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        BEGIN
            IF p_ticket_id IS NULL OR p_claim_token IS NULL
               OR p_extension_seconds IS NULL
               OR p_extension_seconds < 1 OR p_extension_seconds > 900 THEN
                RAISE EXCEPTION 'Delivery lease renewal input is invalid'
                    USING ERRCODE = '22023';
            END IF;

            UPDATE request_engine.identity_recovery_delivery_tickets
               SET lease_until = lease_until
                   + make_interval(secs => p_extension_seconds),
                   updated_at = clock_timestamp()
             WHERE id = p_ticket_id
               AND claim_token = p_claim_token
