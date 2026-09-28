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
               AND status = 'sending'
               AND lease_until > clock_timestamp();

            RETURN FOUND;
        END
        $$;


ALTER FUNCTION request_platform.renew_identity_recovery_delivery_ticket_lease(p_ticket_id uuid, p_claim_token uuid, p_extension_seconds integer) OWNER TO request_platform_control_definer;

--
-- Name: resolve_platform_provider_secret(uuid, text); Type: FUNCTION; Schema: request_platform; Owner: request_platform_control_definer
--

CREATE FUNCTION request_platform.resolve_platform_provider_secret(p_binding_id uuid, p_capability_key text) RETURNS TABLE(binding_id uuid, secret_id uuid, purpose text, backend text, backend_version integer, status text, revision bigint)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        DECLARE
            v_ignore_actor uuid;
            v_ignore_method text;
            v_ignore_correlation uuid;
        BEGIN
            IF p_binding_id IS NULL
               OR p_capability_key NOT IN (
                   'platform.configuration.validate',
                   'platform.provider.test'
               )
            THEN
                RAISE EXCEPTION 'Platform provider secret resolution input is invalid'
                    USING ERRCODE = '22023';
            END IF;

            SELECT actor_id, actor_method, correlation_id
              INTO v_ignore_actor, v_ignore_method, v_ignore_correlation
              FROM request_platform.assert_platform_configuration_actor(
                  p_capability_key
              );

            RETURN QUERY
            SELECT
                binding.id,
                binding.secret_id,
                binding.purpose,
                binding.backend,
                binding.backend_version,
                binding.status,
                binding.revision
              FROM request_engine.platform_secret_bindings AS binding
             WHERE binding.id = p_binding_id;

            IF NOT FOUND THEN
                RAISE EXCEPTION 'Platform secret binding does not exist'
                    USING ERRCODE = 'P0002';
            END IF;
        END
        $$;


ALTER FUNCTION request_platform.resolve_platform_provider_secret(p_binding_id uuid, p_capability_key text) OWNER TO request_platform_control_definer;

--
-- Name: retry_identity_recovery_delivery_ticket(uuid, uuid, integer, text); Type: FUNCTION; Schema: request_platform; Owner: request_platform_control_definer
--

CREATE FUNCTION request_platform.retry_identity_recovery_delivery_ticket(p_ticket_id uuid, p_claim_token uuid, p_delay_seconds integer, p_error_class text) RETURNS text
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        DECLARE
            v_case_id uuid;
            v_status text;
            v_revision_before bigint;
            v_revision_after bigint;
        BEGIN
            IF p_ticket_id IS NULL OR p_claim_token IS NULL
               OR p_delay_seconds IS NULL
               OR p_delay_seconds < 0 OR p_delay_seconds > 86400
               OR p_error_class IS NULL
               OR length(btrim(p_error_class)) NOT BETWEEN 1 AND 80 THEN
                RAISE EXCEPTION 'Delivery retry input is invalid'
                    USING ERRCODE = '22023';
            END IF;

            UPDATE request_engine.identity_recovery_delivery_tickets
               SET status = CASE
                       WHEN attempt_count >= max_attempts THEN 'failed'
                       ELSE 'pending'
                   END,
                   next_attempt_at = clock_timestamp() + make_interval(secs => p_delay_seconds),
                   claim_token = NULL,
                   lease_until = NULL,
                   last_error_class = btrim(p_error_class),
                   updated_at = clock_timestamp()
             WHERE id = p_ticket_id
               AND claim_token = p_claim_token
               AND status = 'sending'
            RETURNING case_id, status INTO v_case_id, v_status;
            IF NOT FOUND THEN
                RETURN 'stale';
            END IF;

            IF v_status = 'pending' THEN
                UPDATE request_engine.identity_recovery_cases
                   SET delivery_status = 'pending',
                       revision = revision + 1,
                       updated_at = clock_timestamp()
                 WHERE id = v_case_id
                   AND status = 'issued';
                RETURN 'pending';
            END IF;

            UPDATE request_engine.identity_recovery_cases
               SET delivery_status = 'failed',
                   revision = revision + 1,
                   updated_at = clock_timestamp()
             WHERE id = v_case_id
               AND status = 'issued'
            RETURNING revision - 1, revision INTO v_revision_before, v_revision_after;
            IF FOUND THEN
                INSERT INTO request_engine.platform_identity_recovery_facts (
                    id,
                    case_id,
                    action,
                    actor_principal_id,
                    actor_authentication_method,
                    reason_code,
                    external_case_reference,
                    revision_before,
                    revision_after,
                    correlation_id,
                    capability_key,
                    idempotency_key_digest,
                    intent_digest
                ) VALUES (
                    uuidv7(),
                    v_case_id,
                    'delivery_failed',
                    NULL,
                    NULL,
                    NULL,
                    NULL,
                    v_revision_before,
                    v_revision_after,
                    NULL,
                    'platform.identity.recovery_delivery',
                    NULL,
                    NULL
                );
            END IF;
            RETURN 'dead';
        END
        $$;


ALTER FUNCTION request_platform.retry_identity_recovery_delivery_ticket(p_ticket_id uuid, p_claim_token uuid, p_delay_seconds integer, p_error_class text) OWNER TO request_platform_control_definer;

--
-- Name: revoke_identity_recovery_case(uuid, bigint, text, text, text); Type: FUNCTION; Schema: request_platform; Owner: request_platform_control_definer
--

CREATE FUNCTION request_platform.revoke_identity_recovery_case(p_case_id uuid, p_expected_revision bigint, p_reason_code text, p_idempotency_key_digest text, p_intent_digest text) RETURNS TABLE(case_id uuid, target_native_identity_id uuid, status text, delivery_status text, revision bigint, issuance_generation integer, approval_expires_at timestamp with time zone, proof_expires_at timestamp with time zone, created_at timestamp with time zone, approved_at timestamp with time zone, issued_at timestamp with time zone, consumed_at timestamp with time zone, revoked_at timestamp with time zone)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $_$
        DECLARE
            v_actor_id uuid;
            v_actor_method text;
            v_correlation_id uuid;
            v_replay record;
            v_case record;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
            IF p_case_id IS NULL OR p_expected_revision IS NULL
               OR p_expected_revision < 1
               OR p_reason_code IS NULL
               OR length(btrim(p_reason_code)) NOT BETWEEN 1 AND 80
               OR p_idempotency_key_digest IS NULL
               OR p_idempotency_key_digest !~ '^[0-9a-f]{64}$'
               OR p_intent_digest IS NULL
               OR p_intent_digest !~ '^[0-9a-f]{64}$' THEN
                RAISE EXCEPTION 'Identity recovery revocation input is invalid'
                    USING ERRCODE = '22023';
            END IF;

            SELECT actor_id, actor_method, correlation_id
              INTO v_actor_id, v_actor_method, v_correlation_id
              FROM request_platform.assert_platform_identity_actor('platform.identity.recover');

            SELECT fact.case_id, fact.intent_digest
              INTO v_replay
              FROM request_engine.platform_identity_recovery_facts AS fact
             WHERE fact.actor_principal_id = v_actor_id
               AND fact.action = 'revoke'
               AND fact.idempotency_key_digest = p_idempotency_key_digest;
            IF FOUND THEN
                IF v_replay.intent_digest <> p_intent_digest THEN
                    RAISE EXCEPTION
                        'Idempotency key was already used for another recovery revocation'
                        USING ERRCODE = '23505';
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
            IF v_case.status IN ('consumed', 'revoked') THEN
                RAISE EXCEPTION 'Identity recovery case is already terminal'
                    USING ERRCODE = '55000';
            END IF;
            IF v_case.revision <> p_expected_revision THEN
                RAISE EXCEPTION 'Identity recovery case revision is stale'
                    USING ERRCODE = '40001';
            END IF;

            IF v_case.status = 'issued' THEN
                UPDATE request_engine.native_recovery_intents
                   SET status = 'revoked',
                       revoked_at = clock_timestamp()
                 WHERE id = v_case.recovery_intent_id
                   AND native_recovery_intents.status = 'pending';
                UPDATE request_engine.identity_recovery_delivery_tickets
                   SET status = 'cancelled',
                       claim_token = NULL,
                       lease_until = NULL,
                       updated_at = clock_timestamp()
                 WHERE identity_recovery_delivery_tickets.case_id = p_case_id
                   AND identity_recovery_delivery_tickets.status IN ('pending', 'sending');
            END IF;

            UPDATE request_engine.identity_recovery_cases
               SET status = 'revoked',
                   revoked_at = clock_timestamp(),
                   revoke_reason_code = btrim(p_reason_code),
                   revision = identity_recovery_cases.revision + 1,
                   updated_at = clock_timestamp()
             WHERE id = p_case_id;
            INSERT INTO request_engine.platform_identity_recovery_facts (
                id,
                case_id,
                action,
                actor_principal_id,
                actor_authentication_method,
                reason_code,
                external_case_reference,
                revision_before,
                revision_after,
                correlation_id,
                capability_key,
                idempotency_key_digest,
                intent_digest
            ) VALUES (
                uuidv7(),
                p_case_id,
                'revoke',
                v_actor_id,
                v_actor_method,
                btrim(p_reason_code),
                v_case.evidence_reference,
                v_case.revision,
                v_case.revision + 1,
                v_correlation_id,
                'platform.identity.recover',
                p_idempotency_key_digest,
                p_intent_digest
            );
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
             WHERE recovery_case.id = p_case_id;
        END
        $_$;


ALTER FUNCTION request_platform.revoke_identity_recovery_case(p_case_id uuid, p_expected_revision bigint, p_reason_code text, p_idempotency_key_digest text, p_intent_digest text) OWNER TO request_platform_control_definer;

--
-- Name: revoke_platform_owner_invitation(uuid, text, text, text); Type: FUNCTION; Schema: request_platform; Owner: request_platform_control_definer
--

CREATE FUNCTION request_platform.revoke_platform_owner_invitation(p_invitation_id uuid, p_reason_code text, p_idempotency_key_digest text, p_intent_digest text) RETURNS bigint
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $_$
        DECLARE
            v_actor_id uuid;
            v_correlation_id uuid;
            v_invitation record;
            v_replay record;
            v_revision_before bigint;
        BEGIN
            SELECT actor_id, correlation_id
              INTO v_actor_id, v_correlation_id
              FROM request_platform.assert_platform_owner_actor(
                  'platform.owner.provision'
              );

            IF p_invitation_id IS NULL
               OR p_reason_code IS NULL
               OR length(btrim(p_reason_code)) NOT BETWEEN 1 AND 80
               OR p_idempotency_key_digest !~ '^[0-9a-f]{64}$'
               OR p_intent_digest !~ '^[0-9a-f]{64}$'
            THEN
                RAISE EXCEPTION 'Platform Owner invitation revocation input is invalid'
                    USING ERRCODE = '22023';
            END IF;

            SELECT fact.revision_after, fact.intent_digest
              INTO v_replay
              FROM request_engine.platform_owner_invitation_facts AS fact
             WHERE fact.actor_principal_id = v_actor_id
               AND fact.action = 'revoke'
               AND fact.idempotency_key_digest = p_idempotency_key_digest;
            IF FOUND THEN
                IF v_replay.intent_digest <> p_intent_digest THEN
                    RAISE EXCEPTION 'Idempotency key conflicts with another revocation'
                        USING ERRCODE = '23505';
                END IF;
                RETURN v_replay.revision_after;
            END IF;

            SELECT invitation.id, invitation.status, invitation.revision,
                   invitation.native_identity_id
              INTO v_invitation
              FROM request_engine.platform_owner_invitations AS invitation
             WHERE invitation.id = p_invitation_id
             FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Platform Owner invitation does not exist'
                    USING ERRCODE = '22023';
            END IF;
            IF v_invitation.status = 'consumed' THEN
                RAISE EXCEPTION 'Activated Platform Owner invitation cannot be revoked'
                    USING ERRCODE = '22023';
            END IF;
            IF v_invitation.status = 'revoked' THEN
                RETURN v_invitation.revision;
            END IF;

            v_revision_before := v_invitation.revision;
            UPDATE request_engine.platform_owner_invitations
               SET status = 'revoked',
                   revision = revision + 1,
                   revoked_at = clock_timestamp()
             WHERE id = v_invitation.id
            RETURNING revision INTO v_invitation.revision;

            INSERT INTO request_engine.platform_owner_invitation_facts (
                invitation_id, action, actor_principal_id, native_identity_id,
                revision_before, revision_after, correlation_id, reason_code,
                idempotency_key_digest, intent_digest
            ) VALUES (
                v_invitation.id, 'revoke', v_actor_id, v_invitation.native_identity_id,
                v_revision_before, v_invitation.revision, v_correlation_id,
                btrim(p_reason_code), p_idempotency_key_digest, p_intent_digest
            );
            RETURN v_invitation.revision;
        END
        $_$;


ALTER FUNCTION request_platform.revoke_platform_owner_invitation(p_invitation_id uuid, p_reason_code text, p_idempotency_key_digest text, p_intent_digest text) OWNER TO request_platform_control_definer;

--
-- Name: revoke_platform_secret_binding(uuid, bigint, integer, text, text); Type: FUNCTION; Schema: request_platform; Owner: request_platform_control_definer
--

CREATE FUNCTION request_platform.revoke_platform_secret_binding(p_binding_id uuid, p_expected_revision bigint, p_expected_backend_version integer, p_idempotency_key_digest text, p_intent_digest text) RETURNS TABLE(binding_id uuid, revision bigint, backend_version integer, status text)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $_$
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
                    'p7/idempotency/'
                    || v_actor_id::text
                    || '/platform.secret.revoke/'
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

            UPDATE request_engine.platform_secret_bindings AS binding
               SET status = 'revoked',
                   revision = binding.revision + 1,
                   revoked_at = clock_timestamp()
             WHERE binding.id = p_binding_id
            RETURNING binding.revision INTO v_revision;

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
        $_$;


ALTER FUNCTION request_platform.revoke_platform_secret_binding(p_binding_id uuid, p_expected_revision bigint, p_expected_backend_version integer, p_idempotency_key_digest text, p_intent_digest text) OWNER TO request_platform_control_definer;

--
-- Name: select_initial_controller_policy(text); Type: FUNCTION; Schema: request_platform; Owner: request_platform_control_definer
--

CREATE FUNCTION request_platform.select_initial_controller_policy(p_policy_key text) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        BEGIN
            IF p_policy_key IS NULL OR NOT EXISTS (
                SELECT 1 FROM request_engine.initial_controller_policies p
                 WHERE p.policy_key = p_policy_key
            ) THEN
                RAISE EXCEPTION 'Unknown initial controller policy' USING ERRCODE = '22023';
            END IF;
            PERFORM set_config('request_engine.initial_controller_policy', p_policy_key, true);
        END $$;


ALTER FUNCTION request_platform.select_initial_controller_policy(p_policy_key text) OWNER TO request_platform_control_definer;

--
-- Name: set_setup_pending_identity(uuid, uuid, text, text); Type: FUNCTION; Schema: request_platform; Owner: request_platform_control_definer
--

CREATE FUNCTION request_platform.set_setup_pending_identity(p_native_identity_id uuid, p_setup_session_id uuid, p_login_handle text, p_verifier text) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $_$
        DECLARE
            v_usable boolean;
        BEGIN
            IF p_native_identity_id IS NULL
               OR p_setup_session_id IS NULL
               OR p_login_handle IS NULL
               OR length(btrim(p_login_handle)) NOT BETWEEN 1 AND 320
               OR p_verifier IS NULL
               OR length(p_verifier) <= 32
               OR NOT (p_verifier LIKE 'scrypt$%' OR p_verifier LIKE '$argon2id$%')
            THEN
                RETURN false;
            END IF;

            SELECT (session.status = 'pending'
                    AND session.expires_at > clock_timestamp()
                    AND instance.state = 'unclaimed')
              INTO v_usable
              FROM request_engine.setup_sessions AS session
              JOIN request_engine.platform_instance AS instance
                ON instance.id = session.instance_id
             WHERE session.id = p_setup_session_id;
            IF v_usable IS NOT TRUE THEN
                RETURN false;
            END IF;

            IF EXISTS (
                SELECT 1 FROM request_engine.setup_pending_identity
                 WHERE setup_session_id = p_setup_session_id
            ) THEN
                UPDATE request_engine.setup_pending_identity
                   SET login_handle = btrim(p_login_handle),
                       verifier = p_verifier
                 WHERE setup_session_id = p_setup_session_id
                   AND status = 'pending';
                RETURN FOUND;
            END IF;

            INSERT INTO request_engine.setup_pending_identity (
                id, setup_session_id, login_handle, verifier
            ) VALUES (
