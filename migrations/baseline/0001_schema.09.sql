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
-- Name: review_controller_policy_adoption(uuid); Type: FUNCTION; Schema: request_platform; Owner: request_platform_control_definer
--

CREATE FUNCTION request_platform.review_controller_policy_adoption(p_request_id uuid) RETURNS TABLE(request_id uuid, organization_id uuid, controller_principal_id uuid, source_policy_key text, target_policy_key text, expected_authority_revision bigint, request_revision bigint, reason text, created_at timestamp with time zone, expires_at timestamp with time zone, current_authority_revision bigint, proposed_capabilities text[], revoked_capabilities text[])
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'request_platform', 'pg_temp'
    AS $$
        DECLARE
            v_actor uuid;
            v_actor_revision bigint;
            v_actor_binding uuid;
            v_request record;
            v_authority_revision bigint;
            v_target jsonb;
        BEGIN
            v_actor:=NULLIF(current_setting(
                'request_engine.authenticated_principal_id',true),'')::uuid;
            v_actor_revision:=NULLIF(current_setting(
                'request_engine.authority_revision',true),'')::bigint;
            v_actor_binding:=NULLIF(current_setting(
                'request_engine.identity_binding_id',true),'')::uuid;
            IF v_actor IS NULL OR v_actor_revision IS NULL OR v_actor_binding IS NULL
               OR NOT EXISTS(
                   SELECT 1 FROM request_engine.principals p
                   JOIN request_engine.identity_bindings b ON b.id=v_actor_binding
                     AND b.principal_id=p.id AND b.principal_plane='platform'
                     AND b.organization_id IS NULL AND b.status='active'
                   JOIN request_engine.principal_authority_grants g ON g.principal_id=p.id
                   WHERE p.id=v_actor AND p.principal_plane='platform'
                     AND p.principal_kind='human' AND p.active
                     AND p.authority_revision=v_actor_revision
                     AND g.principal_plane='platform' AND g.authority_plane='platform'
                     AND g.capability_key='platform.organization.adopt_initial_controller_policy'
                     AND g.status='active'
               ) THEN
                RAISE EXCEPTION 'Current Platform Owner may not review adoption'
                    USING ERRCODE='42501';
            END IF;
            SELECT r.id,r.organization_id,r.controller_principal_id,r.source_policy_key,
                   r.target_policy_key,r.expected_authority_revision,r.revision,r.reason,
                   r.created_at,r.expires_at
              INTO v_request
              FROM request_engine.controller_policy_adoption_requests r
             WHERE r.id=p_request_id AND r.status='pending'
               AND r.expires_at>clock_timestamp();
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Adoption request unavailable' USING ERRCODE='P0002';
            END IF;
            SELECT p.authority_revision INTO v_authority_revision
              FROM request_engine.principals p
             WHERE p.id=v_request.controller_principal_id
               AND p.organization_id=v_request.organization_id AND p.active;
            IF NOT FOUND OR v_authority_revision<>v_request.expected_authority_revision THEN
                RAISE EXCEPTION 'Consenting controller authority has changed' USING ERRCODE='40001';
            END IF;
            SELECT p.grants INTO v_target FROM request_engine.initial_controller_policies p
             WHERE p.policy_key=v_request.target_policy_key;
            RETURN QUERY SELECT v_request.id,v_request.organization_id,
                v_request.controller_principal_id,v_request.source_policy_key,
                v_request.target_policy_key,v_request.expected_authority_revision,
                v_request.revision,v_request.reason,v_request.created_at,v_request.expires_at,
                v_authority_revision,
                COALESCE((SELECT array_agg(g.capability_key ORDER BY g.capability_key)
                  FROM jsonb_to_recordset(v_target)
                    AS g(capability_key text,authority_plane text,delegable boolean)
                 WHERE NOT EXISTS(SELECT 1 FROM request_engine.principal_authority_grants a
                    WHERE a.organization_id=v_request.organization_id
                      AND a.principal_id=v_request.controller_principal_id
                      AND a.capability_key=g.capability_key AND a.status='active')),
                    ARRAY[]::text[]),
                COALESCE((SELECT array_agg(g.capability_key ORDER BY g.capability_key)
                  FROM jsonb_to_recordset(v_target)
                    AS g(capability_key text,authority_plane text,delegable boolean)
                 WHERE EXISTS(SELECT 1 FROM request_engine.principal_authority_grants r
                    WHERE r.organization_id=v_request.organization_id
                      AND r.principal_id=v_request.controller_principal_id
                      AND r.capability_key=g.capability_key AND r.status='revoked')
                   AND NOT EXISTS(SELECT 1 FROM request_engine.principal_authority_grants a
                    WHERE a.organization_id=v_request.organization_id
                      AND a.principal_id=v_request.controller_principal_id
                      AND a.capability_key=g.capability_key AND a.status='active')),
                    ARRAY[]::text[]);
        END $$;


ALTER FUNCTION request_platform.review_controller_policy_adoption(p_request_id uuid) OWNER TO request_platform_control_definer;

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
-- Name: agent_credential_metadata(uuid); Type: FUNCTION; Schema: request_read; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_read.agent_credential_metadata(p_target uuid) RETURNS TABLE(credential_id uuid, status text, revision bigint, expires_at timestamp with time zone)
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
            SELECT c.id,c.status,c.revision,c.expires_at
              FROM request_engine.agent_profiles profile
              JOIN request_engine.workload_credentials c
                ON c.workload_identity_id=profile.workload_identity_id
             WHERE profile.organization_id=request_engine.current_organization_id()
               AND profile.principal_id=p_target AND c.status='active'
               AND EXISTS(SELECT 1 FROM request_engine.principals caller
                    JOIN request_engine.principal_authority_grants g
                      ON g.organization_id=caller.organization_id AND g.principal_id=caller.id
                     AND g.status='active' AND g.authority_plane='tenant_control'
                     AND g.capability_key='agent.read'
                    WHERE caller.organization_id=request_engine.current_organization_id()
                      AND caller.id=NULLIF(current_setting(
                        'request_engine.authenticated_principal_id',true),'')::uuid
                      AND caller.principal_kind='human' AND caller.active)
             ORDER BY c.id
        $$;


ALTER FUNCTION request_read.agent_credential_metadata(p_target uuid) OWNER TO request_engine_schema_owner;

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

--
-- Name: staff_controller_is_effective(uuid); Type: FUNCTION; Schema: request_read; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_read.staff_controller_is_effective(p_principal_id uuid) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
            SELECT CASE WHEN EXISTS (
                SELECT 1 FROM request_engine.principals actor
                JOIN request_engine.staff_memberships membership
                  ON membership.organization_id = actor.organization_id
                 AND membership.principal_id = actor.id
                 AND membership.status = 'active'
                JOIN request_engine.principal_authority_grants grant_row
                  ON grant_row.organization_id = actor.organization_id
                 AND grant_row.principal_id = actor.id
                 AND grant_row.capability_key IN (
                     'staff.plan_authority', 'staff.manage_authority'
                 )
                 AND grant_row.authority_plane = 'tenant_control'
                 AND grant_row.status = 'active'
                WHERE actor.organization_id = request_engine.current_organization_id()
                  AND actor.id = request_engine.current_authenticated_principal_id()
                  AND actor.active AND actor.principal_kind = 'human'
            ) THEN request_engine.principal_is_effective_tenant_controller(
                request_engine.current_organization_id(), p_principal_id
            ) ELSE false END
        $$;


ALTER FUNCTION request_read.staff_controller_is_effective(p_principal_id uuid) OWNER TO request_engine_schema_owner;

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
    change_xid xid8 DEFAULT pg_current_xact_id(),
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
-- Name: COLUMN outbox_messages.change_xid; Type: COMMENT; Schema: request_engine; Owner: request_engine_schema_owner
--

COMMENT ON COLUMN request_engine.outbox_messages.change_xid IS 'Top-level xid8 of the appending transaction; change-feed snapshot cursor primitive.';


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
-- Name: controller_policy_adoption_facts; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.controller_policy_adoption_facts (
    id uuid DEFAULT uuidv7() NOT NULL,
    request_id uuid NOT NULL,
    organization_id uuid NOT NULL,
    controller_principal_id uuid CONSTRAINT controller_policy_adoption_fac_controller_principal_id_not_null NOT NULL,
    controller_binding_id uuid NOT NULL,
    platform_approver_principal_id uuid CONSTRAINT controller_policy_adoption__platform_approver_principa_not_null NOT NULL,
    source_policy_key text NOT NULL,
    target_policy_key text NOT NULL,
    authority_revision_before bigint CONSTRAINT controller_policy_adoption_f_authority_revision_before_not_null NOT NULL,
    authority_revision_after bigint CONSTRAINT controller_policy_adoption_fa_authority_revision_after_not_null NOT NULL,
    added_capabilities text[] NOT NULL,
    idempotency_key_digest text CONSTRAINT controller_policy_adoption_fact_idempotency_key_digest_not_null NOT NULL,
    intent_digest text NOT NULL,
    platform_authority_revision bigint CONSTRAINT controller_policy_adoption__platform_authority_revisio_not_null NOT NULL,
    correlation_id uuid NOT NULL,
    applied_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    controller_native_identity_id uuid,
    controller_recovery_epoch bigint,
    CONSTRAINT controller_policy_adoption_fa_platform_authority_revision_check CHECK ((platform_authority_revision > 0)),
    CONSTRAINT controller_policy_adoption_fact_authority_revision_before_check CHECK ((authority_revision_before > 0)),
    CONSTRAINT controller_policy_adoption_fact_recovery_snapshot_ck CHECK ((((controller_native_identity_id IS NULL) = (controller_recovery_epoch IS NULL)) AND ((controller_recovery_epoch IS NULL) OR (controller_recovery_epoch >= 0)))),
    CONSTRAINT controller_policy_adoption_facts_added_capabilities_check CHECK ((cardinality(added_capabilities) > 0)),
    CONSTRAINT controller_policy_adoption_facts_check CHECK ((authority_revision_after > authority_revision_before)),
    CONSTRAINT controller_policy_adoption_facts_idempotency_key_digest_check CHECK ((idempotency_key_digest ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT controller_policy_adoption_facts_intent_digest_check CHECK ((intent_digest ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT controller_policy_adoption_facts_target_policy_key_check CHECK ((target_policy_key = ANY (ARRAY['tenant-controller-v6'::text, 'tenant-controller-v7'::text, 'tenant-controller-v8'::text, 'tenant-controller-v9'::text])))
);

ALTER TABLE ONLY request_engine.controller_policy_adoption_facts FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.controller_policy_adoption_facts OWNER TO request_engine_schema_owner;

--
-- Name: controller_policy_adoption_requests; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.controller_policy_adoption_requests (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    controller_principal_id uuid CONSTRAINT controller_policy_adoption_req_controller_principal_id_not_null NOT NULL,
    controller_binding_id uuid CONSTRAINT controller_policy_adoption_reque_controller_binding_id_not_null NOT NULL,
    source_policy_key text NOT NULL,
    target_policy_key text NOT NULL,
    expected_authority_revision bigint CONSTRAINT controller_policy_adoption__expected_authority_revisio_not_null NOT NULL,
    reason text NOT NULL,
    idempotency_key_digest text CONSTRAINT controller_policy_adoption_requ_idempotency_key_digest_not_null NOT NULL,
    intent_digest text NOT NULL,
    withdrawn_key_digest text,
    withdrawn_intent_digest text,
    correlation_id uuid NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    revision bigint DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    closed_at timestamp with time zone,
    controller_native_identity_id uuid,
    controller_recovery_epoch bigint,
    CONSTRAINT controller_policy_adoption_re_expected_authority_revision_check CHECK ((expected_authority_revision > 0)),
    CONSTRAINT controller_policy_adoption_request_idempotency_key_digest_check CHECK ((idempotency_key_digest ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT controller_policy_adoption_request_recovery_snapshot_ck CHECK ((((controller_native_identity_id IS NULL) = (controller_recovery_epoch IS NULL)) AND ((status <> 'pending'::text) OR (controller_native_identity_id IS NOT NULL)) AND ((controller_recovery_epoch IS NULL) OR (controller_recovery_epoch >= 0)))),
    CONSTRAINT controller_policy_adoption_request_time_ck CHECK (((expires_at > created_at) AND (expires_at <= (created_at + '24:00:00'::interval)))),
    CONSTRAINT controller_policy_adoption_requests_intent_digest_check CHECK ((intent_digest ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT controller_policy_adoption_requests_reason_check CHECK (((length(btrim(reason)) >= 1) AND (length(btrim(reason)) <= 500))),
    CONSTRAINT controller_policy_adoption_requests_revision_check CHECK ((revision > 0)),
    CONSTRAINT controller_policy_adoption_requests_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'withdrawn'::text, 'expired'::text, 'applied'::text]))),
    CONSTRAINT controller_policy_adoption_requests_target_policy_key_check CHECK ((target_policy_key = ANY (ARRAY['tenant-controller-v6'::text, 'tenant-controller-v7'::text, 'tenant-controller-v8'::text, 'tenant-controller-v9'::text]))),
    CONSTRAINT controller_policy_adoption_status_time_ck CHECK ((((status = 'pending'::text) AND (closed_at IS NULL)) OR ((status = ANY (ARRAY['withdrawn'::text, 'expired'::text, 'applied'::text])) AND (closed_at IS NOT NULL)))),
    CONSTRAINT controller_policy_adoption_withdrawal_shape_ck CHECK ((((status = 'withdrawn'::text) = ((closed_at IS NOT NULL) AND (withdrawn_key_digest IS NOT NULL) AND (withdrawn_intent_digest IS NOT NULL))) OR ((status <> 'withdrawn'::text) AND (withdrawn_key_digest IS NULL) AND (withdrawn_intent_digest IS NULL))))
);

ALTER TABLE ONLY request_engine.controller_policy_adoption_requests FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.controller_policy_adoption_requests OWNER TO request_engine_schema_owner;

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
