    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
            SELECT s.id,
                   s.native_identity_id,
                   i.identity_authority_id,
                   s.password_credential_id,
                   pc.status,
                   s.webauthn_credential_id,
                   wc.status,
                   s.token_digest,
                   s.session_epoch,
                   i.session_epoch,
                   s.status,
                   i.status,
                   a.status,
                   s.authentication_methods,
                   s.authentication_assurance,
                   s.user_verified,
                   s.recovery_derived,
                   coalesce(rs.state = 'recovery_restricted', false),
                   s.expires_at,
                   s.created_at,
                   s.last_seen_at,
                   s.last_authenticated_at
              FROM request_engine.native_sessions AS s
              JOIN request_engine.native_identities AS i
                ON i.id = s.native_identity_id
              LEFT JOIN request_engine.native_credentials AS pc
                ON pc.id = s.password_credential_id
               AND pc.native_identity_id = s.native_identity_id
              LEFT JOIN request_engine.webauthn_credentials AS wc
                ON wc.id = s.webauthn_credential_id
               AND wc.native_identity_id = s.native_identity_id
              LEFT JOIN request_engine.native_identity_recovery_state AS rs
                ON rs.native_identity_id = s.native_identity_id
              JOIN request_engine.identity_authorities AS a
                ON a.id = i.identity_authority_id
               AND a.kind = 'native'
             WHERE s.id = p_session_id
        $$;


ALTER FUNCTION request_auth.read_native_session(p_session_id uuid) OWNER TO request_engine_schema_owner;

--
-- Name: read_oidc_authorities(); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.read_oidc_authorities() RETURNS TABLE(id uuid, issuer_or_environment text, configuration_ref text)
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
            SELECT id,
                   issuer_or_environment,
                   configuration_ref
              FROM request_engine.identity_authorities
             WHERE kind = 'oidc'
               AND status = 'active'
        $$;


ALTER FUNCTION request_auth.read_oidc_authorities() OWNER TO request_engine_schema_owner;

--
-- Name: read_platform_identity_bindings(uuid, text); Type: FUNCTION; Schema: request_auth; Owner: request_platform_definer
--

CREATE FUNCTION request_auth.read_platform_identity_bindings(p_identity_authority_id uuid, p_subject_id text) RETURNS TABLE(binding_id uuid, identity_authority_id uuid, subject_id text, principal_id uuid, principal_plane text, organization_id uuid, status text, revision bigint)
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
            SELECT b.id,
                   b.identity_authority_id,
                   b.subject_id,
                   b.principal_id,
                   b.principal_plane,
                   b.organization_id,
                   b.status,
                   b.revision
              FROM request_engine.identity_bindings AS b
             WHERE b.identity_authority_id = p_identity_authority_id
               AND b.subject_id = p_subject_id
               AND b.principal_plane = 'platform'
               AND b.organization_id IS NULL
        $$;


ALTER FUNCTION request_auth.read_platform_identity_bindings(p_identity_authority_id uuid, p_subject_id text) OWNER TO request_platform_definer;

--
-- Name: read_recovery_code_set_summary(uuid); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.read_recovery_code_set_summary(p_native_identity_id uuid) RETURNS TABLE(set_id uuid, version integer, status text, created_at timestamp with time zone, total_codes integer, remaining_codes integer)
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
            SELECT code_set.id,
                   code_set.version,
                   code_set.status,
                   code_set.created_at,
                   count(code.id)::integer,
                   count(code.id) FILTER (WHERE code.used_at IS NULL)::integer
              FROM request_engine.recovery_code_sets AS code_set
              LEFT JOIN request_engine.recovery_codes AS code
                ON code.set_id = code_set.id
             WHERE code_set.native_identity_id = p_native_identity_id
             GROUP BY code_set.id, code_set.version, code_set.status, code_set.created_at
             ORDER BY code_set.version DESC
        $$;


ALTER FUNCTION request_auth.read_recovery_code_set_summary(p_native_identity_id uuid) OWNER TO request_engine_schema_owner;

--
-- Name: read_webauthn_challenge(bytea, text); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.read_webauthn_challenge(p_challenge_digest bytea, p_purpose text) RETURNS TABLE(challenge_id uuid, native_identity_id uuid, session_id uuid, setup_session_id uuid, expires_at timestamp with time zone)
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
            SELECT challenge.id,
                   challenge.native_identity_id,
                   challenge.session_id,
                   challenge.setup_session_id,
                   challenge.expires_at
              FROM request_engine.webauthn_challenges AS challenge
             WHERE challenge.challenge_digest = p_challenge_digest
               AND challenge.purpose = p_purpose
               AND challenge.status = 'pending'
               AND challenge.expires_at > clock_timestamp()
        $$;


ALTER FUNCTION request_auth.read_webauthn_challenge(p_challenge_digest bytea, p_purpose text) OWNER TO request_engine_schema_owner;

--
-- Name: read_webauthn_credential(bytea); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.read_webauthn_credential(p_credential_id_bytes bytea) RETURNS TABLE(id uuid, native_identity_id uuid, credential_id bytea, public_key bytea, sign_count bigint, aaguid text, backup_eligible boolean, backup_state boolean, user_verified boolean, status text)
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
            SELECT credential.id,
                   credential.native_identity_id,
                   credential.credential_id,
                   credential.public_key,
                   credential.sign_count,
                   credential.aaguid,
                   credential.backup_eligible,
                   credential.backup_state,
                   credential.user_verified,
                   credential.status
              FROM request_engine.webauthn_credentials AS credential
             WHERE credential.credential_id = p_credential_id_bytes
        $$;


ALTER FUNCTION request_auth.read_webauthn_credential(p_credential_id_bytes bytea) OWNER TO request_engine_schema_owner;

--
-- Name: read_webauthn_credentials(uuid); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.read_webauthn_credentials(p_native_identity_id uuid) RETURNS TABLE(id uuid, credential_id bytea, public_key bytea, sign_count bigint, aaguid text, backup_eligible boolean, backup_state boolean, user_verified boolean, status text)
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
            SELECT credential.id,
                   credential.credential_id,
                   credential.public_key,
                   credential.sign_count,
                   credential.aaguid,
                   credential.backup_eligible,
                   credential.backup_state,
                   credential.user_verified,
                   credential.status
              FROM request_engine.webauthn_credentials AS credential
             WHERE credential.native_identity_id = p_native_identity_id
        $$;


ALTER FUNCTION request_auth.read_webauthn_credentials(p_native_identity_id uuid) OWNER TO request_engine_schema_owner;

--
-- Name: read_workload_credential(uuid); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.read_workload_credential(p_credential_id uuid) RETURNS TABLE(credential_id uuid, workload_identity_id uuid, identity_authority_id uuid, workload_kind text, token_digest bytea, credential_status text, identity_status text, authority_status text, expires_at timestamp with time zone)
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
            SELECT credential.id,
                   identity.id,
                   identity.identity_authority_id,
                   identity.workload_kind,
                   credential.token_digest,
                   credential.status,
                   identity.status,
                   authority.status,
                   credential.expires_at
              FROM request_engine.workload_credentials AS credential
              JOIN request_engine.workload_identities AS identity
                ON identity.id = credential.workload_identity_id
              JOIN request_engine.identity_authorities AS authority
                ON authority.id = identity.identity_authority_id
             WHERE credential.id = p_credential_id
               AND authority.kind = 'workload'
        $$;


ALTER FUNCTION request_auth.read_workload_credential(p_credential_id uuid) OWNER TO request_engine_schema_owner;

--
-- Name: reauthenticate_native_session(uuid, uuid); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.reauthenticate_native_session(p_session_id uuid, p_credential_id uuid) RETURNS timestamp with time zone
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
        DECLARE
            v_native_identity_id uuid;
            v_status text;
            v_expires_at timestamptz;
            v_session_epoch bigint;
            v_authenticated_at timestamptz;
        BEGIN
            IF p_session_id IS NULL OR p_credential_id IS NULL THEN
                RETURN NULL;
            END IF;

            SELECT session.native_identity_id, session.status, session.expires_at,
                   session.session_epoch
              INTO v_native_identity_id, v_status, v_expires_at, v_session_epoch
              FROM request_engine.native_sessions AS session
             WHERE session.id = p_session_id
               AND session.password_credential_id = p_credential_id
             FOR UPDATE;
            IF NOT FOUND
               OR v_status <> 'active'
               OR v_expires_at <= clock_timestamp() THEN
                RETURN NULL;
            END IF;

            PERFORM 1
              FROM request_engine.native_identities AS identity
              JOIN request_engine.identity_authorities AS authority
                ON authority.id = identity.identity_authority_id
             WHERE identity.id = v_native_identity_id
               AND identity.status = 'active'
               AND identity.session_epoch = v_session_epoch
               AND authority.kind = 'native'
               AND authority.status = 'active';
            IF NOT FOUND THEN
                RETURN NULL;
            END IF;

            UPDATE request_engine.native_sessions
               SET last_authenticated_at = clock_timestamp(),
                   last_seen_at = clock_timestamp()
             WHERE id = p_session_id
             RETURNING last_authenticated_at INTO v_authenticated_at;
            RETURN v_authenticated_at;
        END
        $$;


ALTER FUNCTION request_auth.reauthenticate_native_session(p_session_id uuid, p_credential_id uuid) OWNER TO request_engine_schema_owner;

--
-- Name: rehash_native_password_verifier(uuid, uuid, text); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.rehash_native_password_verifier(p_credential_id uuid, p_native_identity_id uuid, p_new_verifier text) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $_$
        DECLARE
            v_updated bigint;
        BEGIN
            IF p_credential_id IS NULL
               OR p_native_identity_id IS NULL
               OR p_new_verifier IS NULL
               OR p_new_verifier NOT LIKE '$argon2id$%'
               OR length(p_new_verifier) <= 32
            THEN
                RETURN false;
            END IF;

            PERFORM 1
              FROM request_engine.identity_authorities AS authority
              JOIN request_engine.native_identities AS native_identity
                ON native_identity.identity_authority_id = authority.id
             WHERE native_identity.id = p_native_identity_id
               AND authority.kind = 'native' AND authority.status = 'active'
             FOR SHARE OF authority;
            IF NOT FOUND THEN RETURN false; END IF;

            UPDATE request_engine.native_credentials
               SET verifier = p_new_verifier
             WHERE id = p_credential_id
               AND native_identity_id = p_native_identity_id
               AND kind = 'password'
               AND status = 'active'
               AND verifier LIKE 'scrypt$%';
            GET DIAGNOSTICS v_updated = ROW_COUNT;
            RETURN v_updated > 0;
        END
        $_$;


ALTER FUNCTION request_auth.rehash_native_password_verifier(p_credential_id uuid, p_native_identity_id uuid, p_new_verifier text) OWNER TO request_engine_schema_owner;

--
-- Name: renew_native_recovery_delivery_request_lease(uuid, uuid, integer); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.renew_native_recovery_delivery_request_lease(p_request_id uuid, p_claim_token uuid, p_extension_seconds integer) RETURNS boolean
    LANGUAGE sql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
            UPDATE request_engine.native_recovery_delivery_requests AS request
               SET lease_until = clock_timestamp()
                   + make_interval(secs => p_extension_seconds),
                   updated_at = clock_timestamp()
             WHERE p_request_id IS NOT NULL
               AND p_claim_token IS NOT NULL
               AND p_extension_seconds BETWEEN 1 AND 900
               AND request.id = p_request_id
               AND request.claim_token = p_claim_token
               AND request.status = 'sending'
            RETURNING true
        $$;


ALTER FUNCTION request_auth.renew_native_recovery_delivery_request_lease(p_request_id uuid, p_claim_token uuid, p_extension_seconds integer) OWNER TO request_engine_schema_owner;

--
-- Name: retry_native_recovery_delivery_request(uuid, uuid, integer, text); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.retry_native_recovery_delivery_request(p_request_id uuid, p_claim_token uuid, p_delay_seconds integer, p_error_class text) RETURNS text
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
        DECLARE
            v_row record;
            v_next_status text;
        BEGIN
            IF p_request_id IS NULL
               OR p_claim_token IS NULL
               OR p_delay_seconds IS NULL
               OR p_delay_seconds < 0 OR p_delay_seconds > 86400
               OR p_error_class IS NULL
               OR length(btrim(p_error_class)) NOT BETWEEN 1 AND 80
            THEN
                RETURN 'stale';
            END IF;

            SELECT request.native_identity_id,
                   request.recovery_address_id,
                   request.generation,
                   request.recovery_intent_id,
                   request.attempt_count,
                   request.max_attempts,
                   request.request_expires_at
              INTO v_row
              FROM request_engine.native_recovery_delivery_requests AS request
             WHERE request.id = p_request_id
               AND request.claim_token = p_claim_token
               AND request.status = 'sending'
             FOR UPDATE;
            IF NOT FOUND THEN
                RETURN 'stale';
            END IF;

            v_next_status := CASE
                WHEN v_row.attempt_count >= v_row.max_attempts
                  OR v_row.request_expires_at <= clock_timestamp()
                THEN 'failed'
                ELSE 'pending'
            END;

            UPDATE request_engine.native_recovery_delivery_requests AS request
               SET status = v_next_status,
                   next_attempt_at = clock_timestamp()
                       + make_interval(secs => p_delay_seconds),
                   claim_token = NULL,
                   lease_until = NULL,
                   last_error_class = btrim(p_error_class),
                   updated_at = clock_timestamp()
             WHERE request.id = p_request_id;

            IF v_next_status = 'failed' AND v_row.recovery_intent_id IS NOT NULL THEN
                UPDATE request_engine.native_recovery_intents AS intent
                   SET status = 'revoked',
                       revoked_at = clock_timestamp()
                 WHERE intent.id = v_row.recovery_intent_id
                   AND intent.status = 'pending';
            END IF;

            INSERT INTO request_engine.native_recovery_delivery_facts (
                request_id,
                native_identity_id,
                recovery_address_id,
                generation,
                event_kind,
                error_class
            ) VALUES (
                p_request_id,
                v_row.native_identity_id,
                v_row.recovery_address_id,
                v_row.generation,
                CASE
                    WHEN v_next_status = 'failed' THEN 'delivery_failed'
                    ELSE 'retry_scheduled'
                END,
                btrim(p_error_class)
            );
            RETURN CASE WHEN v_next_status = 'failed' THEN 'dead' ELSE 'retry' END;
        END
        $$;


ALTER FUNCTION request_auth.retry_native_recovery_delivery_request(p_request_id uuid, p_claim_token uuid, p_delay_seconds integer, p_error_class text) OWNER TO request_engine_schema_owner;

--
-- Name: revoke_native_recovery_address(uuid, uuid); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.revoke_native_recovery_address(p_native_identity_id uuid, p_recovery_address_id uuid) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
        DECLARE
            v_address_status text;
        BEGIN
            SELECT address.status
              INTO v_address_status
              FROM request_engine.native_recovery_addresses AS address
             WHERE address.id = p_recovery_address_id
               AND address.native_identity_id = p_native_identity_id
             FOR UPDATE;
            IF NOT FOUND OR v_address_status = 'revoked' THEN
                RETURN false;
            END IF;

            UPDATE request_engine.native_recovery_address_verifications
               SET status = 'revoked',
                   revoked_at = clock_timestamp()
             WHERE recovery_address_id = p_recovery_address_id
               AND status = 'pending';

            UPDATE request_engine.native_recovery_addresses
               SET status = 'revoked',
                   revision = revision + 1,
                   revoked_at = clock_timestamp()
             WHERE id = p_recovery_address_id;

            INSERT INTO request_engine.native_recovery_address_facts (
                native_identity_id,
                recovery_address_id,
                event_kind,
                correlation_id
            ) VALUES (
                p_native_identity_id,
                p_recovery_address_id,
                'address_revoked',
                NULLIF(current_setting('request_engine.correlation_id', true), '')::uuid
            );
            RETURN true;
        END
        $$;


ALTER FUNCTION request_auth.revoke_native_recovery_address(p_native_identity_id uuid, p_recovery_address_id uuid) OWNER TO request_engine_schema_owner;

--
-- Name: revoke_native_session(uuid, uuid, text); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.revoke_native_session(p_native_identity_id uuid, p_session_id uuid, p_reason text) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
        DECLARE
            v_updated bigint;
        BEGIN
            UPDATE request_engine.native_sessions
               SET status = 'revoked',
                   revoked_at = clock_timestamp(),
                   revocation_reason = p_reason
             WHERE id = p_session_id
               AND native_identity_id = p_native_identity_id
               AND status = 'active';
            GET DIAGNOSTICS v_updated = ROW_COUNT;
            RETURN v_updated > 0;
        END
        $$;


ALTER FUNCTION request_auth.revoke_native_session(p_native_identity_id uuid, p_session_id uuid, p_reason text) OWNER TO request_engine_schema_owner;

--
-- Name: revoke_native_sessions(uuid, text); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.revoke_native_sessions(p_native_identity_id uuid, p_reason text) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
        BEGIN
            UPDATE request_engine.native_identities
               SET session_epoch = session_epoch + 1,
                   revision = revision + 1,
                   updated_at = clock_timestamp()
             WHERE id = p_native_identity_id;
            IF NOT FOUND THEN
                RETURN false;
            END IF;
            UPDATE request_engine.native_sessions
               SET status = 'revoked',
                   revoked_at = clock_timestamp(),
                   revocation_reason = p_reason
             WHERE native_identity_id = p_native_identity_id
               AND status = 'active';
            RETURN true;
        END
        $$;


ALTER FUNCTION request_auth.revoke_native_sessions(p_native_identity_id uuid, p_reason text) OWNER TO request_engine_schema_owner;

--
-- Name: revoke_recovery_code_set(uuid, text); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.revoke_recovery_code_set(p_set_id uuid, p_reason text) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
        DECLARE
            v_set request_engine.recovery_code_sets%ROWTYPE;
        BEGIN
            IF p_set_id IS NULL
               OR p_reason IS NULL
               OR length(btrim(p_reason)) NOT BETWEEN 1 AND 200
            THEN
                RETURN false;
            END IF;

            SELECT code_set.* INTO v_set
              FROM request_engine.recovery_code_sets AS code_set
             WHERE code_set.id = p_set_id
             FOR UPDATE;
            IF NOT FOUND OR v_set.status <> 'active' THEN
                RETURN false;
            END IF;

            UPDATE request_engine.recovery_code_sets
               SET status = 'revoked',
                   revision = revision + 1,
                   revoked_at = clock_timestamp()
             WHERE id = p_set_id;

            INSERT INTO request_engine.platform_recovery_code_facts (
                event_kind, set_id, native_identity_id, setup_session_id,
                actor_principal_id, actor_authentication_method, capability_key,
                correlation_id
            ) VALUES (
                'set_revoked', p_set_id, v_set.native_identity_id, v_set.setup_session_id,
                NULLIF(
                    current_setting('request_engine.authenticated_principal_id', true), ''
                )::uuid,
                NULLIF(current_setting('request_engine.authentication_method', true), ''),
                'platform.recovery_codes.manage',
                NULLIF(current_setting('request_engine.correlation_id', true), '')::uuid
            );
            RETURN true;
        END
        $$;


ALTER FUNCTION request_auth.revoke_recovery_code_set(p_set_id uuid, p_reason text) OWNER TO request_engine_schema_owner;

--
-- Name: revoke_webauthn_credential(uuid, uuid, text); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.revoke_webauthn_credential(p_credential_id uuid, p_native_identity_id uuid, p_reason text) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
        DECLARE
            v_updated bigint;
        BEGIN
            IF p_reason IS NULL OR length(btrim(p_reason)) NOT BETWEEN 1 AND 200 THEN
                RETURN false;
            END IF;
            UPDATE request_engine.webauthn_credentials
               SET status = 'revoked',
                   revision = revision + 1,
                   revoked_at = clock_timestamp()
             WHERE id = p_credential_id
               AND native_identity_id = p_native_identity_id
               AND status = 'active';
            GET DIAGNOSTICS v_updated = ROW_COUNT;
            IF v_updated = 0 THEN
                RETURN false;
            END IF;
            -- Any active session whose proven methods include WebAuthn loses the
            -- factor's authority, including password sessions that stepped up.
            UPDATE request_engine.native_sessions
               SET status = 'revoked',
                   revoked_at = clock_timestamp(),
                   revocation_reason = 'webauthn_credential_revoked'
             WHERE status = 'active'
               AND (
                   webauthn_credential_id = p_credential_id
                   OR (
                       native_identity_id = p_native_identity_id
                       AND 'webauthn' = ANY(authentication_methods)
                   )
               );
            RETURN true;
        END
        $$;


ALTER FUNCTION request_auth.revoke_webauthn_credential(p_credential_id uuid, p_native_identity_id uuid, p_reason text) OWNER TO request_engine_schema_owner;

--
-- Name: rotate_native_password(uuid, uuid, uuid, text, text); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.rotate_native_password(p_native_identity_id uuid, p_expected_credential_id uuid, p_new_credential_id uuid, p_new_verifier text, p_reason text) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
        DECLARE
            v_identity_status text;
            v_credential_status text;
        BEGIN
            -- Authority is locked before identity; SHARE conflicts with status UPDATE.
            PERFORM 1
              FROM request_engine.identity_authorities AS authority
              JOIN request_engine.native_identities AS native_identity
                ON native_identity.identity_authority_id = authority.id
             WHERE native_identity.id = p_native_identity_id
               AND authority.kind = 'native' AND authority.status = 'active'
             FOR SHARE OF authority;
            IF NOT FOUND THEN RETURN false; END IF;

            SELECT status INTO v_identity_status
              FROM request_engine.native_identities
             WHERE id = p_native_identity_id
             FOR UPDATE;
            IF NOT FOUND OR v_identity_status <> 'active' THEN
                RETURN false;
            END IF;

            SELECT status INTO v_credential_status
              FROM request_engine.native_credentials
             WHERE id = p_expected_credential_id
               AND native_identity_id = p_native_identity_id
               AND kind = 'password'
             FOR UPDATE;
            IF NOT FOUND OR v_credential_status <> 'active' THEN
                RETURN false;
            END IF;

            UPDATE request_engine.native_credentials
               SET status = 'revoked',
                   revision = revision + 1,
                   rotated_at = clock_timestamp(),
                   revoked_at = clock_timestamp()
             WHERE id = p_expected_credential_id;
            INSERT INTO request_engine.native_credentials (
                id, native_identity_id, verifier
            ) VALUES (
                p_new_credential_id, p_native_identity_id, p_new_verifier
            );
            UPDATE request_engine.native_identities
               SET session_epoch = session_epoch + 1,
                   revision = revision + 1,
                   updated_at = clock_timestamp()
             WHERE id = p_native_identity_id;
            UPDATE request_engine.native_sessions
               SET status = 'revoked',
                   revoked_at = clock_timestamp(),
                   revocation_reason = p_reason
             WHERE native_identity_id = p_native_identity_id
               AND status = 'active';
            RETURN true;
        END
        $$;


ALTER FUNCTION request_auth.rotate_native_password(p_native_identity_id uuid, p_expected_credential_id uuid, p_new_credential_id uuid, p_new_verifier text, p_reason text) OWNER TO request_engine_schema_owner;

--
-- Name: touch_native_session(uuid, integer); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.touch_native_session(p_session_id uuid, p_min_interval_seconds integer) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        DECLARE
            v_updated boolean;
        BEGIN
            IF p_session_id IS NULL THEN
                RETURN false;
            END IF;
            UPDATE request_engine.native_sessions
               SET last_seen_at = clock_timestamp()
             WHERE id = p_session_id
               AND status = 'active'
               AND (last_seen_at IS NULL
                    OR last_seen_at < clock_timestamp()
                       - make_interval(secs => GREATEST(p_min_interval_seconds, 0)))
             RETURNING true INTO v_updated;
            RETURN COALESCE(v_updated, false);
        END
        $$;


ALTER FUNCTION request_auth.touch_native_session(p_session_id uuid, p_min_interval_seconds integer) OWNER TO request_engine_schema_owner;

--
-- Name: verify_native_recovery_address(uuid, bytea); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.verify_native_recovery_address(p_verification_id uuid, p_token_digest bytea) RETURNS uuid
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
        DECLARE
            v_address_id uuid;
            v_identity_id uuid;
            v_address_status text;
        BEGIN
            IF p_verification_id IS NULL
               OR p_token_digest IS NULL
               OR octet_length(p_token_digest) <> 32
            THEN
                RETURN NULL;
            END IF;

            SELECT verification.recovery_address_id
              INTO v_address_id
              FROM request_engine.native_recovery_address_verifications AS verification
             WHERE verification.id = p_verification_id
               AND verification.token_digest = p_token_digest
               AND verification.status = 'pending'
               AND verification.expires_at > clock_timestamp()
             FOR UPDATE;
            IF NOT FOUND THEN
                RETURN NULL;
            END IF;

            SELECT address.native_identity_id, address.status
              INTO v_identity_id, v_address_status
              FROM request_engine.native_recovery_addresses AS address
             WHERE address.id = v_address_id
             FOR UPDATE;
            IF NOT FOUND OR v_address_status <> 'pending' THEN
                RETURN NULL;
            END IF;

            UPDATE request_engine.native_recovery_address_verifications
               SET status = 'consumed',
                   consumed_at = clock_timestamp()
             WHERE id = p_verification_id;

            UPDATE request_engine.native_recovery_addresses
               SET status = 'verified',
                   revision = revision + 1,
                   verified_at = clock_timestamp()
             WHERE id = v_address_id;

            INSERT INTO request_engine.native_recovery_address_facts (
                native_identity_id,
                recovery_address_id,
                event_kind,
                correlation_id
            ) VALUES (
                v_identity_id,
                v_address_id,
                'address_verified',
                NULLIF(current_setting('request_engine.correlation_id', true), '')::uuid
            );
            RETURN v_identity_id;
        END
        $$;


ALTER FUNCTION request_auth.verify_native_recovery_address(p_verification_id uuid, p_token_digest bytea) OWNER TO request_engine_schema_owner;

--
-- Name: acquire_idempotency(uuid, uuid, text, text, text); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.acquire_idempotency(p_organization_id uuid, p_principal_id uuid, p_capability text, p_idempotency_key text, p_request_fingerprint text) RETURNS TABLE(idempotency_id uuid, status text, result_data jsonb, replay boolean)
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_record request_engine.idempotency_records%ROWTYPE;
    v_capability text;
BEGIN
    IF p_organization_id IS DISTINCT FROM request_engine.current_organization_id() THEN
        RAISE EXCEPTION 'organization context mismatch'
            USING ERRCODE = '42501';
    END IF;

    v_capability := CASE p_capability
        WHEN 'appointments.attendance.accepted'
            THEN 'booking.record_attendance_response'
        WHEN 'appointments.attendance.declined'
            THEN 'booking.record_attendance_response'
        ELSE p_capability
    END;

    INSERT INTO request_engine.idempotency_records (
        organization_id,
        principal_id,
        capability,
        idempotency_key,
        request_fingerprint
    )
    VALUES (
        p_organization_id,
        p_principal_id,
        v_capability,
        p_idempotency_key,
        p_request_fingerprint
    )
    ON CONFLICT (organization_id, principal_id, capability, idempotency_key)
    DO NOTHING;

    SELECT *
      INTO v_record
      FROM request_engine.idempotency_records i
     WHERE i.organization_id = p_organization_id
       AND i.principal_id = p_principal_id
       AND i.capability = v_capability
       AND i.idempotency_key = p_idempotency_key
     FOR UPDATE;

    IF v_record.request_fingerprint <> p_request_fingerprint THEN
        RAISE EXCEPTION 'idempotency key reused with different request fingerprint'
            USING ERRCODE = 'P1001';
    END IF;

    RETURN QUERY SELECT
        v_record.id,
        v_record.status,
        v_record.result_data,
        v_record.status = 'completed';
END
$$;


ALTER FUNCTION request_cmd.acquire_idempotency(p_organization_id uuid, p_principal_id uuid, p_capability text, p_idempotency_key text, p_request_fingerprint text) OWNER TO request_engine_schema_owner;

--
-- Name: assert_integration_manager(text); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.assert_integration_manager(p_capability text) RETURNS uuid
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        BEGIN
            IF p_capability IS NULL OR p_capability NOT IN (
                'integration.provision', 'integration.manage_authority', 'integration.suspend'
            ) THEN
                RAISE EXCEPTION 'Unsupported integration control capability'
                    USING ERRCODE = '22023';
            END IF;
            RETURN request_engine.assert_staff_manager(p_capability);
        END $$;


ALTER FUNCTION request_cmd.assert_integration_manager(p_capability text) OWNER TO request_engine_schema_owner;

--
-- Name: cancel_scheduled_action(uuid, uuid); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.cancel_scheduled_action(p_organization_id uuid, p_action_id uuid) RETURNS text
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_status text;
BEGIN
    IF p_organization_id IS DISTINCT FROM request_engine.current_organization_id() THEN
        RAISE EXCEPTION 'organization context mismatch'
            USING ERRCODE = '42501';
    END IF;

    UPDATE request_engine.scheduled_actions
       SET status = 'cancelled',
           claim_token = NULL,
           lease_until = NULL,
           updated_at = clock_timestamp()
     WHERE organization_id = p_organization_id
       AND id = p_action_id
       AND status IN ('pending', 'leased')
    RETURNING status INTO v_status;

    IF FOUND THEN
        RETURN v_status;
    END IF;

    SELECT status
      INTO v_status
      FROM request_engine.scheduled_actions
     WHERE organization_id = p_organization_id
       AND id = p_action_id;

    RETURN COALESCE(v_status, 'not_found');
END
$$;


ALTER FUNCTION request_cmd.cancel_scheduled_action(p_organization_id uuid, p_action_id uuid) OWNER TO request_engine_schema_owner;

--
-- Name: claim_outbox_messages(integer, interval); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.claim_outbox_messages(p_limit integer, p_lease interval DEFAULT '00:01:00'::interval) RETURNS TABLE(message_id uuid, organization_id uuid, claim_token uuid, event_type text, schema_version integer, aggregate_kind text, aggregate_id uuid, payload jsonb, attempt_count integer, lease_until timestamp with time zone)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
BEGIN
    IF p_limit <= 0 OR p_limit > 500 THEN
        RAISE EXCEPTION 'claim limit must be between 1 and 500'
            USING ERRCODE = '22023';
    END IF;
    IF p_lease <= interval '0 seconds' OR p_lease > interval '15 minutes' THEN
        RAISE EXCEPTION 'lease must be > 0 and <= 15 minutes'
            USING ERRCODE = '22023';
    END IF;

    UPDATE request_engine.outbox_messages o
       SET status = 'dead',
           claim_token = NULL,
           lease_until = NULL,
           last_error_class = COALESCE(last_error_class, 'max_attempts_exhausted'),
           updated_at = clock_timestamp()
     WHERE o.attempt_count >= o.max_attempts
       AND (
           (o.status = 'pending' AND o.next_attempt_at <= clock_timestamp()) OR
           (o.status = 'leased' AND o.lease_until <= clock_timestamp())
       );

    RETURN QUERY
    WITH ranked AS MATERIALIZED (
        SELECT o.id,
               o.organization_id,
               CASE WHEN o.status = 'pending' THEN o.next_attempt_at ELSE o.lease_until END AS due_at,
               row_number() OVER (
                   PARTITION BY o.organization_id
                   ORDER BY
                       CASE WHEN o.status = 'pending' THEN o.next_attempt_at ELSE o.lease_until END,
                       o.id
               ) AS tenant_rank
          FROM request_engine.outbox_messages o
         WHERE o.attempt_count < o.max_attempts
           AND (
               (o.status = 'pending' AND o.next_attempt_at <= statement_timestamp()) OR
               (o.status = 'leased' AND o.lease_until <= statement_timestamp())
           )
    ), candidates AS (
        SELECT o.id
          FROM ranked r
          JOIN request_engine.outbox_messages o ON o.id = r.id
         WHERE o.attempt_count < o.max_attempts
           AND (
               (o.status = 'pending' AND o.next_attempt_at <= clock_timestamp()) OR
               (o.status = 'leased' AND o.lease_until <= clock_timestamp())
           )
         ORDER BY r.tenant_rank, r.due_at, r.organization_id, r.id
         FOR UPDATE OF o SKIP LOCKED
         LIMIT p_limit
    ), claimed AS (
        UPDATE request_engine.outbox_messages o
           SET status = 'leased',
               claim_token = uuidv7(),
               lease_until = clock_timestamp() + p_lease,
               attempt_count = o.attempt_count + 1,
               updated_at = clock_timestamp()
          FROM candidates c
         WHERE o.id = c.id
           AND o.attempt_count < o.max_attempts
           AND (
               (o.status = 'pending' AND o.next_attempt_at <= clock_timestamp()) OR
               (o.status = 'leased' AND o.lease_until <= clock_timestamp())
           )
        RETURNING o.*
    )
    SELECT c.id,
           c.organization_id,
           c.claim_token,
           c.event_type,
           c.schema_version,
           c.aggregate_kind,
           c.aggregate_id,
           c.payload,
           c.attempt_count,
           c.lease_until
      FROM claimed c
      JOIN ranked r ON r.id = c.id
     ORDER BY r.tenant_rank, r.due_at, r.organization_id, r.id;
END
$$;


ALTER FUNCTION request_cmd.claim_outbox_messages(p_limit integer, p_lease interval) OWNER TO request_engine_schema_owner;

--
-- Name: claim_provider_events(integer, interval); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.claim_provider_events(p_limit integer, p_lease interval DEFAULT '00:01:00'::interval) RETURNS TABLE(provider_event_row_id uuid, organization_id uuid, claim_token uuid, provider_key text, connection_key text, provider_event_id text, payload_hash text, payload jsonb, attempt_count integer, lease_until timestamp with time zone)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
BEGIN
    IF p_limit <= 0 OR p_limit > 500 THEN
        RAISE EXCEPTION 'claim limit must be between 1 and 500'
            USING ERRCODE = '22023';
    END IF;
    IF p_lease <= interval '0 seconds' OR p_lease > interval '15 minutes' THEN
        RAISE EXCEPTION 'lease must be > 0 and <= 15 minutes'
            USING ERRCODE = '22023';
    END IF;

    UPDATE request_engine.provider_events e
       SET status = 'dead',
           claim_token = NULL,
           lease_until = NULL,
           last_error_class = COALESCE(last_error_class, 'max_attempts_exhausted'),
           updated_at = clock_timestamp()
     WHERE e.attempt_count >= e.max_attempts
       AND (
           (e.status = 'received' AND e.next_attempt_at <= clock_timestamp()) OR
           (e.status = 'leased' AND e.lease_until <= clock_timestamp())
       );

    RETURN QUERY
    WITH ranked AS MATERIALIZED (
        SELECT e.id,
               e.organization_id,
               CASE WHEN e.status = 'received' THEN e.next_attempt_at ELSE e.lease_until END AS due_at,
               row_number() OVER (
                   PARTITION BY e.organization_id
                   ORDER BY
                       CASE WHEN e.status = 'received' THEN e.next_attempt_at ELSE e.lease_until END,
                       e.id
               ) AS tenant_rank
          FROM request_engine.provider_events e
         WHERE e.attempt_count < e.max_attempts
           AND (
               (e.status = 'received' AND e.next_attempt_at <= statement_timestamp()) OR
               (e.status = 'leased' AND e.lease_until <= statement_timestamp())
           )
    ), candidates AS (
        SELECT e.id
          FROM ranked r
          JOIN request_engine.provider_events e ON e.id = r.id
         WHERE e.attempt_count < e.max_attempts
           AND (
               (e.status = 'received' AND e.next_attempt_at <= clock_timestamp()) OR
               (e.status = 'leased' AND e.lease_until <= clock_timestamp())
           )
         ORDER BY r.tenant_rank, r.due_at, r.organization_id, r.id
         FOR UPDATE OF e SKIP LOCKED
         LIMIT p_limit
    ), claimed AS (
        UPDATE request_engine.provider_events e
           SET status = 'leased',
               claim_token = uuidv7(),
               lease_until = clock_timestamp() + p_lease,
               attempt_count = e.attempt_count + 1,
               updated_at = clock_timestamp()
          FROM candidates c
         WHERE e.id = c.id
           AND e.attempt_count < e.max_attempts
           AND (
               (e.status = 'received' AND e.next_attempt_at <= clock_timestamp()) OR
               (e.status = 'leased' AND e.lease_until <= clock_timestamp())
           )
        RETURNING e.*
    )
    SELECT c.id,
           c.organization_id,
           c.claim_token,
           c.provider_key,
           c.connection_key,
           c.provider_event_id,
           c.payload_hash,
           c.payload,
           c.attempt_count,
           c.lease_until
      FROM claimed c
      JOIN ranked r ON r.id = c.id
     ORDER BY r.tenant_rank, r.due_at, r.organization_id, r.id;
END
$$;


ALTER FUNCTION request_cmd.claim_provider_events(p_limit integer, p_lease interval) OWNER TO request_engine_schema_owner;

--
-- Name: claim_scheduled_actions(integer, interval); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.claim_scheduled_actions(p_limit integer, p_lease interval DEFAULT '00:01:00'::interval) RETURNS TABLE(action_id uuid, organization_id uuid, claim_token uuid, owner_module text, action_type text, action_version integer, subject_kind text, subject_id uuid, payload jsonb, attempt_count integer, lease_until timestamp with time zone)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
BEGIN
    IF p_limit <= 0 OR p_limit > 500 THEN
        RAISE EXCEPTION 'claim limit must be between 1 and 500'
            USING ERRCODE = '22023';
    END IF;
    IF p_lease <= interval '0 seconds' OR p_lease > interval '15 minutes' THEN
        RAISE EXCEPTION 'lease must be > 0 and <= 15 minutes'
            USING ERRCODE = '22023';
    END IF;

    UPDATE request_engine.scheduled_actions s
       SET status = 'dead',
           claim_token = NULL,
           lease_until = NULL,
           last_error_class = COALESCE(last_error_class, 'max_attempts_exhausted'),
           updated_at = clock_timestamp()
     WHERE s.attempt_count >= s.max_attempts
       AND (
           (s.status = 'pending' AND s.next_attempt_at <= clock_timestamp()) OR
           (s.status = 'leased' AND s.lease_until <= clock_timestamp())
       );

    RETURN QUERY
    WITH ranked AS MATERIALIZED (
        SELECT s.id,
               s.organization_id,
               CASE WHEN s.status = 'pending' THEN s.next_attempt_at ELSE s.lease_until END AS due_at,
               row_number() OVER (
                   PARTITION BY s.organization_id
                   ORDER BY
                       CASE WHEN s.status = 'pending' THEN s.next_attempt_at ELSE s.lease_until END,
                       s.id
               ) AS tenant_rank
          FROM request_engine.scheduled_actions s
         WHERE s.attempt_count < s.max_attempts
           AND (
               (s.status = 'pending' AND s.next_attempt_at <= statement_timestamp()) OR
               (s.status = 'leased' AND s.lease_until <= statement_timestamp())
           )
    ), candidates AS (
        SELECT s.id
          FROM ranked r
          JOIN request_engine.scheduled_actions s ON s.id = r.id
         WHERE s.attempt_count < s.max_attempts
           AND (
               (s.status = 'pending' AND s.next_attempt_at <= clock_timestamp()) OR
               (s.status = 'leased' AND s.lease_until <= clock_timestamp())
           )
         ORDER BY r.tenant_rank, r.due_at, r.organization_id, r.id
         FOR UPDATE OF s SKIP LOCKED
         LIMIT p_limit
    ), claimed AS (
        UPDATE request_engine.scheduled_actions s
           SET status = 'leased',
               claim_token = uuidv7(),
               lease_until = clock_timestamp() + p_lease,
               attempt_count = s.attempt_count + 1,
               updated_at = clock_timestamp()
          FROM candidates c
         WHERE s.id = c.id
           AND s.attempt_count < s.max_attempts
           AND (
               (s.status = 'pending' AND s.next_attempt_at <= clock_timestamp()) OR
               (s.status = 'leased' AND s.lease_until <= clock_timestamp())
           )
        RETURNING s.*
    )
    SELECT c.id,
           c.organization_id,
           c.claim_token,
           c.owner_module,
           c.action_type,
           c.action_version,
           c.subject_kind,
           c.subject_id,
           c.payload,
           c.attempt_count,
           c.lease_until
      FROM claimed c
      JOIN ranked r ON r.id = c.id
     ORDER BY r.tenant_rank, r.due_at, r.organization_id, r.id;
END
$$;


ALTER FUNCTION request_cmd.claim_scheduled_actions(p_limit integer, p_lease interval) OWNER TO request_engine_schema_owner;

--
-- Name: complete_idempotency(uuid, jsonb); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.complete_idempotency(p_idempotency_id uuid, p_result_data jsonb) RETURNS boolean
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_updated bigint;
BEGIN
    UPDATE request_engine.idempotency_records
       SET status = 'completed',
           result_data = p_result_data,
           completed_at = clock_timestamp()
     WHERE id = p_idempotency_id
       AND organization_id = request_engine.current_organization_id()
       AND status = 'in_progress';

    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated = 1;
END
$$;


ALTER FUNCTION request_cmd.complete_idempotency(p_idempotency_id uuid, p_result_data jsonb) OWNER TO request_engine_schema_owner;

--
-- Name: complete_outbox_message(uuid, uuid); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.complete_outbox_message(p_message_id uuid, p_claim_token uuid) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_updated bigint;
BEGIN
    UPDATE request_engine.outbox_messages
       SET status = 'delivered',
           claim_token = NULL,
           lease_until = NULL,
           delivered_at = clock_timestamp(),
           updated_at = clock_timestamp()
     WHERE id = p_message_id
       AND status = 'leased'
       AND claim_token = p_claim_token
       AND lease_until > clock_timestamp();

    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated = 1;
END
$$;


ALTER FUNCTION request_cmd.complete_outbox_message(p_message_id uuid, p_claim_token uuid) OWNER TO request_engine_schema_owner;

--
-- Name: complete_provider_event(uuid, uuid); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.complete_provider_event(p_provider_event_row_id uuid, p_claim_token uuid) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_updated bigint;
BEGIN
    UPDATE request_engine.provider_events
       SET status = 'processed',
           claim_token = NULL,
           lease_until = NULL,
           processed_at = clock_timestamp(),
           last_error_class = NULL,
           updated_at = clock_timestamp()
     WHERE id = p_provider_event_row_id
       AND status = 'leased'
       AND claim_token = p_claim_token
       AND lease_until > clock_timestamp();

    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated = 1;
END
$$;


ALTER FUNCTION request_cmd.complete_provider_event(p_provider_event_row_id uuid, p_claim_token uuid) OWNER TO request_engine_schema_owner;

--
-- Name: complete_scheduled_action(uuid, uuid); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.complete_scheduled_action(p_action_id uuid, p_claim_token uuid) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_updated bigint;
BEGIN
    UPDATE request_engine.scheduled_actions
       SET status = 'completed',
           claim_token = NULL,
           lease_until = NULL,
           completed_at = clock_timestamp(),
           updated_at = clock_timestamp()
     WHERE id = p_action_id
       AND status = 'leased'
       AND claim_token = p_claim_token
       AND lease_until > clock_timestamp();

    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated = 1;
END
$$;


ALTER FUNCTION request_cmd.complete_scheduled_action(p_action_id uuid, p_claim_token uuid) OWNER TO request_engine_schema_owner;

--
-- Name: dead_letter_outbox_message(uuid, uuid, text); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.dead_letter_outbox_message(p_message_id uuid, p_claim_token uuid, p_error_class text) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_updated bigint;
BEGIN
    UPDATE request_engine.outbox_messages
       SET status = 'dead',
           claim_token = NULL,
           lease_until = NULL,
           last_error_class = p_error_class,
           updated_at = clock_timestamp()
     WHERE id = p_message_id
       AND status = 'leased'
       AND claim_token = p_claim_token
       AND lease_until > clock_timestamp();

    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated = 1;
END
$$;


ALTER FUNCTION request_cmd.dead_letter_outbox_message(p_message_id uuid, p_claim_token uuid, p_error_class text) OWNER TO request_engine_schema_owner;

--
-- Name: dead_letter_provider_event(uuid, uuid, text); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.dead_letter_provider_event(p_provider_event_row_id uuid, p_claim_token uuid, p_error_class text) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_updated bigint;
BEGIN
    UPDATE request_engine.provider_events
       SET status = 'dead',
           claim_token = NULL,
           lease_until = NULL,
           processed_at = NULL,
           last_error_class = p_error_class,
           updated_at = clock_timestamp()
     WHERE id = p_provider_event_row_id
       AND status = 'leased'
       AND claim_token = p_claim_token
       AND lease_until > clock_timestamp();

    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated = 1;
END
$$;


ALTER FUNCTION request_cmd.dead_letter_provider_event(p_provider_event_row_id uuid, p_claim_token uuid, p_error_class text) OWNER TO request_engine_schema_owner;

--
-- Name: dead_letter_scheduled_action(uuid, uuid, text); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.dead_letter_scheduled_action(p_action_id uuid, p_claim_token uuid, p_error_class text) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_updated bigint;
BEGIN
    UPDATE request_engine.scheduled_actions
       SET status = 'dead',
           claim_token = NULL,
           lease_until = NULL,
           last_error_class = p_error_class,
           updated_at = clock_timestamp()
     WHERE id = p_action_id
       AND status = 'leased'
       AND claim_token = p_claim_token
       AND lease_until > clock_timestamp();

    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated = 1;
END
$$;


ALTER FUNCTION request_cmd.dead_letter_scheduled_action(p_action_id uuid, p_claim_token uuid, p_error_class text) OWNER TO request_engine_schema_owner;

--
-- Name: find_recovery_sweep_scopes(integer); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.find_recovery_sweep_scopes(p_limit integer) RETURNS TABLE(organization_id uuid, service_queue_id uuid)
    LANGUAGE sql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
    SELECT DISTINCT
        sa.organization_id AS organization_id,
        sa.subject_id AS service_queue_id
    FROM request_engine.scheduled_actions sa
    WHERE sa.owner_module = 'operational_recovery'
      AND sa.action_type = 'reassess_recovery_scope'
      AND sa.subject_id IS NOT NULL
    ORDER BY 1, 2
    LIMIT GREATEST(LEAST(COALESCE(p_limit, 0), 500), 0)
$$;


ALTER FUNCTION request_cmd.find_recovery_sweep_scopes(p_limit integer) OWNER TO request_engine_schema_owner;

--
-- Name: lock_outbox_message_claim(uuid, uuid, uuid); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.lock_outbox_message_claim(p_organization_id uuid, p_message_id uuid, p_claim_token uuid) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_found boolean;
BEGIN
    IF p_organization_id IS DISTINCT FROM request_engine.current_organization_id() THEN
        RAISE EXCEPTION 'organization context mismatch'
            USING ERRCODE = '42501';
    END IF;

    SELECT true
      INTO v_found
      FROM request_engine.outbox_messages
     WHERE organization_id = p_organization_id
       AND id = p_message_id
       AND status = 'leased'
       AND claim_token = p_claim_token
       AND lease_until > clock_timestamp()
     FOR UPDATE;

    RETURN COALESCE(v_found, false);
END
$$;


ALTER FUNCTION request_cmd.lock_outbox_message_claim(p_organization_id uuid, p_message_id uuid, p_claim_token uuid) OWNER TO request_engine_schema_owner;

--
-- Name: lock_recovery_source_revision(uuid, uuid); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.lock_recovery_source_revision(p_organization_id uuid, p_service_queue_id uuid) RETURNS bigint
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_revision bigint;
BEGIN
    SELECT revision INTO v_revision
    FROM request_engine.recovery_source_revisions
    WHERE organization_id = p_organization_id
      AND service_queue_id = p_service_queue_id
    FOR UPDATE;
    IF v_revision IS NULL THEN
        RAISE EXCEPTION 'Recovery source revision is not configured for queue %',
            p_service_queue_id
          USING ERRCODE = '23514';
    END IF;
    RETURN v_revision;
END
$$;


ALTER FUNCTION request_cmd.lock_recovery_source_revision(p_organization_id uuid, p_service_queue_id uuid) OWNER TO request_engine_schema_owner;

--
-- Name: lock_scheduled_action_claim(uuid, uuid); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.lock_scheduled_action_claim(p_action_id uuid, p_claim_token uuid) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_found boolean;
BEGIN
    SELECT true
      INTO v_found
      FROM request_engine.scheduled_actions
     WHERE id = p_action_id
       AND status = 'leased'
       AND claim_token = p_claim_token
       AND lease_until > clock_timestamp()
     FOR UPDATE;

    RETURN COALESCE(v_found, false);
END
$$;


ALTER FUNCTION request_cmd.lock_scheduled_action_claim(p_action_id uuid, p_claim_token uuid) OWNER TO request_engine_schema_owner;

--
-- Name: lock_shared_capacity_roots(uuid, uuid[]); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.lock_shared_capacity_roots(p_organization_id uuid, p_resource_ids uuid[]) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_context_organization_id uuid;
    v_requested bigint;
    v_local bigint := 0;
    v_resource_id uuid;
BEGIN
    v_context_organization_id := request_engine.current_organization_id();
    IF v_context_organization_id IS NULL
       OR p_organization_id IS NULL
       OR p_organization_id <> v_context_organization_id
    THEN
        RAISE EXCEPTION 'organization context mismatch'
            USING ERRCODE = '42501';
    END IF;

    SELECT count(DISTINCT value)
      INTO v_requested
      FROM unnest(COALESCE(p_resource_ids, ARRAY[]::uuid[])) AS input(value)
     WHERE value IS NOT NULL;

    IF v_requested = 0 THEN
        RETURN;
    END IF;

    -- Validate tenant ownership and take every local root in the same stable
    -- order used by Booking. Counting while locking prevents this protected
    -- function from ever acquiring a shared root first.
    FOR v_resource_id IN
        SELECT r.id
          FROM request_engine.resources r
         WHERE r.organization_id = p_organization_id
           AND r.id = ANY(p_resource_ids)
         ORDER BY r.id
         FOR UPDATE
    LOOP
        v_local := v_local + 1;
    END LOOP;

    IF v_local <> v_requested THEN
        RAISE EXCEPTION 'one or more Resources are not available in tenant context'
            USING ERRCODE = '42501';
    END IF;

    PERFORM 1
      FROM request_engine.shared_capacity_identities s
      JOIN request_engine.shared_capacity_bindings b
        ON b.shared_capacity_identity_id = s.id
       AND b.status = 'active'
     WHERE b.organization_id = p_organization_id
       AND b.resource_id = ANY(p_resource_ids)
       AND s.status = 'active'
     ORDER BY s.id
     FOR UPDATE OF s;
END
$$;


ALTER FUNCTION request_cmd.lock_shared_capacity_roots(p_organization_id uuid, p_resource_ids uuid[]) OWNER TO request_engine_schema_owner;

--
-- Name: mark_queue_entry_service_completed(uuid, uuid, timestamp with time zone); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.mark_queue_entry_service_completed(p_organization_id uuid, p_queue_entry_id uuid, p_completed_at timestamp with time zone) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        BEGIN
            IF request_engine.current_organization_id() IS DISTINCT FROM p_organization_id THEN
                RAISE EXCEPTION 'queue service-complete transition rejects foreign tenant authority'
                    USING ERRCODE = '23514';
            END IF;

            UPDATE request_engine.queue_entries
               SET status = 'completed',
                   completed_at = p_completed_at,
                   revision = revision + 1,
                   updated_at = clock_timestamp()
             WHERE organization_id = p_organization_id
               AND id = p_queue_entry_id
               AND status = 'serving';

            IF NOT FOUND THEN
                RAISE EXCEPTION 'QueueEntry % is not serving', p_queue_entry_id
                    USING ERRCODE = '23514';
            END IF;
        END
        $$;


ALTER FUNCTION request_cmd.mark_queue_entry_service_completed(p_organization_id uuid, p_queue_entry_id uuid, p_completed_at timestamp with time zone) OWNER TO request_engine_schema_owner;

--
-- Name: mark_queue_entry_service_started(uuid, uuid, timestamp with time zone); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.mark_queue_entry_service_started(p_organization_id uuid, p_queue_entry_id uuid, p_started_at timestamp with time zone) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        BEGIN
            IF request_engine.current_organization_id() IS DISTINCT FROM p_organization_id THEN
                RAISE EXCEPTION 'queue service-start transition rejects foreign tenant authority'
                    USING ERRCODE = '23514';
            END IF;

            UPDATE request_engine.queue_entries
               SET status = 'serving',
                   service_started_at = p_started_at,
                   completed_at = NULL,
                   revision = revision + 1,
                   updated_at = clock_timestamp()
             WHERE organization_id = p_organization_id
               AND id = p_queue_entry_id
               AND status = 'called';

            IF NOT FOUND THEN
                RAISE EXCEPTION 'QueueEntry % is not callable', p_queue_entry_id
                    USING ERRCODE = '23514';
            END IF;
        END
        $$;


ALTER FUNCTION request_cmd.mark_queue_entry_service_started(p_organization_id uuid, p_queue_entry_id uuid, p_started_at timestamp with time zone) OWNER TO request_engine_schema_owner;

--
-- Name: reject_provider_event(uuid, uuid, text); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.reject_provider_event(p_provider_event_row_id uuid, p_claim_token uuid, p_error_class text) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_updated bigint;
BEGIN
    UPDATE request_engine.provider_events
       SET status = 'rejected',
           claim_token = NULL,
           lease_until = NULL,
           processed_at = clock_timestamp(),
           last_error_class = p_error_class,
           updated_at = clock_timestamp()
     WHERE id = p_provider_event_row_id
       AND status = 'leased'
       AND claim_token = p_claim_token
       AND lease_until > clock_timestamp();

    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated = 1;
END
$$;


ALTER FUNCTION request_cmd.reject_provider_event(p_provider_event_row_id uuid, p_claim_token uuid, p_error_class text) OWNER TO request_engine_schema_owner;

--
-- Name: renew_outbox_message_lease(uuid, uuid, interval); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.renew_outbox_message_lease(p_message_id uuid, p_claim_token uuid, p_extension interval DEFAULT '00:01:00'::interval) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_updated bigint;
BEGIN
    IF p_extension <= interval '0 seconds' OR p_extension > interval '15 minutes' THEN
        RAISE EXCEPTION 'lease extension must be > 0 and <= 15 minutes'
            USING ERRCODE = '22023';
    END IF;
    UPDATE request_engine.outbox_messages
       SET lease_until = clock_timestamp() + p_extension,
           updated_at = clock_timestamp()
     WHERE id = p_message_id
       AND status = 'leased'
       AND claim_token = p_claim_token
       AND lease_until > clock_timestamp();
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated = 1;
END
$$;


ALTER FUNCTION request_cmd.renew_outbox_message_lease(p_message_id uuid, p_claim_token uuid, p_extension interval) OWNER TO request_engine_schema_owner;

--
-- Name: renew_provider_event_lease(uuid, uuid, interval); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.renew_provider_event_lease(p_provider_event_row_id uuid, p_claim_token uuid, p_extension interval DEFAULT '00:01:00'::interval) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_updated bigint;
BEGIN
    IF p_extension <= interval '0 seconds' OR p_extension > interval '15 minutes' THEN
        RAISE EXCEPTION 'lease extension must be > 0 and <= 15 minutes'
            USING ERRCODE = '22023';
    END IF;
    UPDATE request_engine.provider_events
       SET lease_until = clock_timestamp() + p_extension,
           updated_at = clock_timestamp()
     WHERE id = p_provider_event_row_id
       AND status = 'leased'
       AND claim_token = p_claim_token
       AND lease_until > clock_timestamp();
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated = 1;
END
$$;


ALTER FUNCTION request_cmd.renew_provider_event_lease(p_provider_event_row_id uuid, p_claim_token uuid, p_extension interval) OWNER TO request_engine_schema_owner;

--
-- Name: renew_scheduled_action_lease(uuid, uuid, interval); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.renew_scheduled_action_lease(p_action_id uuid, p_claim_token uuid, p_extension interval DEFAULT '00:01:00'::interval) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_updated bigint;
BEGIN
    IF p_extension <= interval '0 seconds' OR p_extension > interval '15 minutes' THEN
        RAISE EXCEPTION 'lease extension must be > 0 and <= 15 minutes'
            USING ERRCODE = '22023';
    END IF;
    UPDATE request_engine.scheduled_actions
       SET lease_until = clock_timestamp() + p_extension,
           updated_at = clock_timestamp()
     WHERE id = p_action_id
       AND status = 'leased'
       AND claim_token = p_claim_token
       AND lease_until > clock_timestamp();
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated = 1;
END
$$;


ALTER FUNCTION request_cmd.renew_scheduled_action_lease(p_action_id uuid, p_claim_token uuid, p_extension interval) OWNER TO request_engine_schema_owner;

--
-- Name: retry_outbox_message(uuid, uuid, timestamp with time zone, text); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.retry_outbox_message(p_message_id uuid, p_claim_token uuid, p_next_attempt_at timestamp with time zone, p_error_class text) RETURNS text
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_attempt_count integer;
    v_max_attempts integer;
    v_status text;
    v_updated bigint;
BEGIN
    SELECT attempt_count, max_attempts
      INTO v_attempt_count, v_max_attempts
      FROM request_engine.outbox_messages
     WHERE id = p_message_id
       AND status = 'leased'
       AND claim_token = p_claim_token
       AND lease_until > clock_timestamp()
     FOR UPDATE;
    IF NOT FOUND THEN
        RETURN 'stale';
    END IF;

    v_status := CASE WHEN v_attempt_count >= v_max_attempts THEN 'dead' ELSE 'pending' END;
    UPDATE request_engine.outbox_messages
       SET status = v_status,
           claim_token = NULL,
           lease_until = NULL,
           next_attempt_at = CASE
               WHEN v_status = 'pending' THEN p_next_attempt_at
               ELSE next_attempt_at
           END,
           last_error_class = p_error_class,
           updated_at = clock_timestamp()
     WHERE id = p_message_id
       AND status = 'leased'
       AND claim_token = p_claim_token
       AND lease_until > clock_timestamp();
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    IF v_updated <> 1 THEN
        RETURN 'stale';
    END IF;
    RETURN v_status;
END
$$;


ALTER FUNCTION request_cmd.retry_outbox_message(p_message_id uuid, p_claim_token uuid, p_next_attempt_at timestamp with time zone, p_error_class text) OWNER TO request_engine_schema_owner;

--
-- Name: retry_outbox_message_after(uuid, uuid, interval, text); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.retry_outbox_message_after(p_message_id uuid, p_claim_token uuid, p_delay interval, p_error_class text) RETURNS text
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_attempt_count integer;
    v_max_attempts integer;
    v_status text;
    v_updated bigint;
BEGIN
    IF p_delay < interval '0 seconds' OR p_delay > interval '24 hours' THEN
        RAISE EXCEPTION 'retry delay must be between 0 and 24 hours'
            USING ERRCODE = '22023';
    END IF;

    SELECT attempt_count, max_attempts
      INTO v_attempt_count, v_max_attempts
      FROM request_engine.outbox_messages
     WHERE id = p_message_id
       AND status = 'leased'
       AND claim_token = p_claim_token
       AND lease_until > clock_timestamp()
     FOR UPDATE;
    IF NOT FOUND THEN
        RETURN 'stale';
    END IF;

    v_status := CASE WHEN v_attempt_count >= v_max_attempts THEN 'dead' ELSE 'pending' END;
    UPDATE request_engine.outbox_messages
       SET status = v_status,
           claim_token = NULL,
           lease_until = NULL,
           next_attempt_at = CASE
               WHEN v_status = 'pending' THEN clock_timestamp() + p_delay
               ELSE next_attempt_at
           END,
           last_error_class = p_error_class,
           updated_at = clock_timestamp()
     WHERE id = p_message_id
       AND status = 'leased'
       AND claim_token = p_claim_token
       AND lease_until > clock_timestamp();
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    IF v_updated <> 1 THEN
        RETURN 'stale';
    END IF;
    RETURN v_status;
END
$$;


ALTER FUNCTION request_cmd.retry_outbox_message_after(p_message_id uuid, p_claim_token uuid, p_delay interval, p_error_class text) OWNER TO request_engine_schema_owner;

--
-- Name: retry_provider_event_after(uuid, uuid, interval, text); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.retry_provider_event_after(p_provider_event_row_id uuid, p_claim_token uuid, p_delay interval, p_error_class text) RETURNS text
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_attempt_count integer;
    v_max_attempts integer;
    v_status text;
    v_updated bigint;
BEGIN
    IF p_delay < interval '0 seconds' OR p_delay > interval '24 hours' THEN
        RAISE EXCEPTION 'retry delay must be between 0 and 24 hours'
            USING ERRCODE = '22023';
    END IF;

    SELECT attempt_count, max_attempts
      INTO v_attempt_count, v_max_attempts
      FROM request_engine.provider_events
     WHERE id = p_provider_event_row_id
       AND status = 'leased'
       AND claim_token = p_claim_token
       AND lease_until > clock_timestamp()
     FOR UPDATE;
    IF NOT FOUND THEN
        RETURN 'stale';
    END IF;

    v_status := CASE WHEN v_attempt_count >= v_max_attempts THEN 'dead' ELSE 'received' END;
    UPDATE request_engine.provider_events
       SET status = v_status,
           claim_token = NULL,
           lease_until = NULL,
           next_attempt_at = CASE
               WHEN v_status = 'received' THEN clock_timestamp() + p_delay
               ELSE next_attempt_at
           END,
           last_error_class = p_error_class,
           updated_at = clock_timestamp()
     WHERE id = p_provider_event_row_id
       AND status = 'leased'
       AND claim_token = p_claim_token
       AND lease_until > clock_timestamp();
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    IF v_updated <> 1 THEN
        RETURN 'stale';
    END IF;
    RETURN v_status;
END
$$;


ALTER FUNCTION request_cmd.retry_provider_event_after(p_provider_event_row_id uuid, p_claim_token uuid, p_delay interval, p_error_class text) OWNER TO request_engine_schema_owner;

--
-- Name: retry_scheduled_action(uuid, uuid, timestamp with time zone, text); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.retry_scheduled_action(p_action_id uuid, p_claim_token uuid, p_next_attempt_at timestamp with time zone, p_error_class text) RETURNS text
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_attempt_count integer;
    v_max_attempts integer;
    v_status text;
    v_updated bigint;
BEGIN
    SELECT attempt_count, max_attempts
      INTO v_attempt_count, v_max_attempts
      FROM request_engine.scheduled_actions
     WHERE id = p_action_id
       AND status = 'leased'
       AND claim_token = p_claim_token
       AND lease_until > clock_timestamp()
     FOR UPDATE;
    IF NOT FOUND THEN
        RETURN 'stale';
    END IF;

    v_status := CASE WHEN v_attempt_count >= v_max_attempts THEN 'dead' ELSE 'pending' END;
    UPDATE request_engine.scheduled_actions
       SET status = v_status,
           claim_token = NULL,
           lease_until = NULL,
           next_attempt_at = CASE
               WHEN v_status = 'pending' THEN p_next_attempt_at
               ELSE next_attempt_at
           END,
           last_error_class = p_error_class,
           updated_at = clock_timestamp()
     WHERE id = p_action_id
       AND status = 'leased'
       AND claim_token = p_claim_token
       AND lease_until > clock_timestamp();
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    IF v_updated <> 1 THEN
        RETURN 'stale';
    END IF;
    RETURN v_status;
END
$$;


ALTER FUNCTION request_cmd.retry_scheduled_action(p_action_id uuid, p_claim_token uuid, p_next_attempt_at timestamp with time zone, p_error_class text) OWNER TO request_engine_schema_owner;

--
-- Name: retry_scheduled_action_after(uuid, uuid, interval, text); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.retry_scheduled_action_after(p_action_id uuid, p_claim_token uuid, p_delay interval, p_error_class text) RETURNS text
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_attempt_count integer;
    v_max_attempts integer;
    v_status text;
    v_updated bigint;
BEGIN
    IF p_delay < interval '0 seconds' OR p_delay > interval '24 hours' THEN
        RAISE EXCEPTION 'retry delay must be between 0 and 24 hours'
            USING ERRCODE = '22023';
    END IF;

    SELECT attempt_count, max_attempts
      INTO v_attempt_count, v_max_attempts
      FROM request_engine.scheduled_actions
     WHERE id = p_action_id
       AND status = 'leased'
       AND claim_token = p_claim_token
       AND lease_until > clock_timestamp()
     FOR UPDATE;
    IF NOT FOUND THEN
        RETURN 'stale';
    END IF;

    v_status := CASE WHEN v_attempt_count >= v_max_attempts THEN 'dead' ELSE 'pending' END;
    UPDATE request_engine.scheduled_actions
       SET status = v_status,
           claim_token = NULL,
           lease_until = NULL,
           next_attempt_at = CASE
               WHEN v_status = 'pending' THEN clock_timestamp() + p_delay
               ELSE next_attempt_at
           END,
           last_error_class = p_error_class,
           updated_at = clock_timestamp()
     WHERE id = p_action_id
       AND status = 'leased'
       AND claim_token = p_claim_token
       AND lease_until > clock_timestamp();
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    IF v_updated <> 1 THEN
        RETURN 'stale';
    END IF;
    RETURN v_status;
END
$$;


ALTER FUNCTION request_cmd.retry_scheduled_action_after(p_action_id uuid, p_claim_token uuid, p_delay interval, p_error_class text) OWNER TO request_engine_schema_owner;

--
-- Name: rotate_integration_credential(uuid, bigint, uuid, bytea, text, timestamp with time zone, text); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.rotate_integration_credential(p_principal_id uuid, p_expected_revision bigint, p_credential_id uuid, p_digest bytea, p_fingerprint text, p_expires_at timestamp with time zone, p_reference text) RETURNS bigint
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $_$
        DECLARE
            v_actor uuid;
            v_revision bigint;
            v_identity uuid;
        BEGIN
            v_actor := request_engine.assert_staff_manager('integration.provision');
            SELECT authority_revision INTO v_revision FROM request_engine.principals
             WHERE id = p_principal_id AND principal_kind = 'integration'
               AND organization_id = request_engine.current_organization_id()
             FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Integration not found' USING ERRCODE = 'P0002';
            END IF;
            IF p_expected_revision IS NULL OR p_expected_revision < 1
               OR p_expires_at IS NULL OR p_expires_at <= clock_timestamp()
               OR p_credential_id IS NULL OR p_digest IS NULL OR octet_length(p_digest) <> 32
               OR p_fingerprint IS NULL OR p_fingerprint !~ '^[0-9a-f]{16}$'
               OR p_reference IS NULL OR length(btrim(p_reference)) NOT BETWEEN 1 AND 500 THEN
                RAISE EXCEPTION 'Invalid credential replacement input' USING ERRCODE = '22023';
            END IF;
            IF v_revision <> p_expected_revision THEN
                RAISE EXCEPTION 'Integration revision is stale' USING ERRCODE = '40001';
            END IF;
            SELECT wi.id INTO v_identity
              FROM request_engine.workload_identities wi
              JOIN request_engine.identity_bindings b
                ON b.subject_id = wi.id::text AND b.identity_authority_id = wi.identity_authority_id
              JOIN request_engine.identity_authorities ia ON ia.id = wi.identity_authority_id
             WHERE b.principal_id = p_principal_id
               AND b.organization_id = request_engine.current_organization_id()
               AND b.status IN ('pending', 'active', 'suspended')
               AND wi.status = 'active' AND wi.workload_kind = 'integration'
               AND ia.status = 'active' AND ia.kind = 'workload'
             FOR UPDATE OF wi FOR SHARE OF b, ia;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Revoked integration or inactive identity authority'
                    USING ERRCODE = '55000';
            END IF;
            UPDATE request_engine.workload_credentials
               SET status = 'revoked', revision = revision + 1, revoked_at = clock_timestamp()
             WHERE workload_identity_id = v_identity AND status = 'active';
            INSERT INTO request_engine.workload_credentials (
                id, workload_identity_id, token_digest, token_fingerprint, expires_at
            ) VALUES (p_credential_id, v_identity, p_digest, p_fingerprint, p_expires_at);
            UPDATE request_engine.principals SET authority_revision = authority_revision + 1
             WHERE id = p_principal_id RETURNING authority_revision INTO v_revision;
            PERFORM request_engine.append_integration_fact(
                p_principal_id, v_actor, 'credential_rotate', p_reference, 'integration.provision'
            );
            RETURN v_revision;
        END $_$;


ALTER FUNCTION request_cmd.rotate_integration_credential(p_principal_id uuid, p_expected_revision bigint, p_credential_id uuid, p_digest bytea, p_fingerprint text, p_expires_at timestamp with time zone, p_reference text) OWNER TO request_engine_schema_owner;

--
-- Name: schedule_recovery_reassessment(uuid, uuid, bigint); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.schedule_recovery_reassessment(p_organization_id uuid, p_service_queue_id uuid, p_revision bigint) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_dedupe_key text;
    v_inserted boolean := false;
    v_context text := COALESCE(
        current_setting('request_engine.organization_id', true),
        ''
    );
BEGIN
    IF p_service_queue_id IS NULL OR p_revision IS NULL OR p_revision <= 0 THEN
        RETURN false;
    END IF;
    IF v_context <> '' AND v_context <> p_organization_id::text THEN
        RAISE EXCEPTION
            'schedule_recovery_reassessment rejects foreign tenant authority'
            USING ERRCODE = '23514';
    END IF;

    v_dedupe_key := format('f5-reassessment:%s:%s', p_service_queue_id, p_revision);

    INSERT INTO request_engine.scheduled_actions (
        organization_id,
        owner_module,
        action_type,
        action_version,
        subject_kind,
        subject_id,
        payload,
        dedupe_key,
        execute_at,
        next_attempt_at,
        max_attempts
    ) VALUES (
        p_organization_id,
        'operational_recovery',
        'reassess_recovery_scope',
        1,
        'ServiceQueue',
        p_service_queue_id,
        jsonb_build_object(
            'service_queue_id', p_service_queue_id::text,
            'source_revision', p_revision
        ),
        v_dedupe_key,
        clock_timestamp(),
        clock_timestamp(),
        8
    )
    ON CONFLICT (organization_id, dedupe_key) DO NOTHING
    RETURNING true INTO v_inserted;

    UPDATE request_engine.scheduled_actions
       SET status = 'cancelled',
           updated_at = clock_timestamp()
     WHERE organization_id = p_organization_id
       AND owner_module = 'operational_recovery'
       AND action_type = 'reassess_recovery_scope'
       AND subject_id = p_service_queue_id
       AND status = 'pending'
       AND dedupe_key <> v_dedupe_key
       AND (payload->>'source_revision')::bigint < p_revision;

    RETURN v_inserted;
END
$$;


ALTER FUNCTION request_cmd.schedule_recovery_reassessment(p_organization_id uuid, p_service_queue_id uuid, p_revision bigint) OWNER TO request_engine_schema_owner;

--
-- Name: acquire_identity_topology_exclusive(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.acquire_identity_topology_exclusive() RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        BEGIN
            PERFORM pg_catalog.pg_advisory_xact_lock(1380274257, 1902476357);
        END
        $$;


ALTER FUNCTION request_engine.acquire_identity_topology_exclusive() OWNER TO request_engine_schema_owner;

--
-- Name: acquire_identity_topology_share(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.acquire_identity_topology_share() RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        BEGIN
            PERFORM pg_catalog.pg_advisory_xact_lock_shared(1380274257, 1902476357);
        END
        $$;


ALTER FUNCTION request_engine.acquire_identity_topology_share() OWNER TO request_engine_schema_owner;

--
-- Name: adopt_platform_owner_v3(); Type: FUNCTION; Schema: request_engine; Owner: request_platform_control_definer
--

CREATE FUNCTION request_engine.adopt_platform_owner_v3() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
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
        $$;


ALTER FUNCTION request_engine.adopt_platform_owner_v3() OWNER TO request_platform_control_definer;

--
-- Name: append_integration_fact(uuid, uuid, text, text, text); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.append_integration_fact(p_principal_id uuid, p_actor_id uuid, p_operation text, p_reference text, p_capability text) RETURNS void
    LANGUAGE sql
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
            INSERT INTO request_engine.integration_governance_facts (
                organization_id, integration_principal_id, actor_principal_id,
                actor_authority_revision, operation, provenance_reference,
                authority_revision, snapshot
            )
            SELECT pr.organization_id, pr.id, actor.id, actor.authority_revision,
                   p_operation, btrim(p_reference), pr.authority_revision,
                   jsonb_build_object(
                       'authority_source', p_capability,
                       'active', pr.active,
                       'grants', COALESCE((
                           SELECT jsonb_agg(jsonb_build_object(
                               'id', g.id, 'capability', g.capability_key,
                               'delegable', g.delegable, 'revision', g.revision
                           ) ORDER BY g.capability_key)
                           FROM request_engine.principal_authority_grants g
                           WHERE g.organization_id = pr.organization_id
                             AND g.principal_id = pr.id AND g.status = 'active'
                       ), '[]'::jsonb),
                       'delegable_ceiling', COALESCE((
                           SELECT jsonb_agg(jsonb_build_object(
                               'id', g.id, 'capability', g.capability_key,
                               'revision', g.revision
                           ) ORDER BY g.capability_key)
                           FROM request_engine.principal_authority_grants g
                           WHERE g.organization_id = pr.organization_id
                             AND g.principal_id = actor.id AND g.status = 'active'
                             AND g.delegable AND g.authority_plane = 'operational'
                       ), '[]'::jsonb),
                       'bindings', COALESCE((
                           SELECT jsonb_agg(jsonb_build_object(
                               'id', b.id, 'authority_id', b.identity_authority_id,
                               'subject_id', b.subject_id, 'status', b.status,
                               'revision', b.revision
                           ) ORDER BY b.id)
                           FROM request_engine.identity_bindings b
                           WHERE b.organization_id = pr.organization_id
                             AND b.principal_id = pr.id
                       ), '[]'::jsonb),
                       'credentials', COALESCE((
                           SELECT jsonb_agg(jsonb_build_object(
                               'id', c.id, 'status', c.status, 'expires_at', c.expires_at
                           ) ORDER BY c.id)
                           FROM request_engine.identity_bindings b
                           JOIN request_engine.workload_credentials c
                             ON c.workload_identity_id::text = b.subject_id
                           WHERE b.organization_id = pr.organization_id
                             AND b.principal_id = pr.id AND c.status = 'active'
                       ), '[]'::jsonb)
                   )
              FROM request_engine.principals pr
              JOIN request_engine.principals actor
                ON actor.id = p_actor_id AND actor.organization_id = pr.organization_id
             WHERE pr.id = p_principal_id
               AND pr.organization_id = request_engine.current_organization_id()
        $$;


ALTER FUNCTION request_engine.append_integration_fact(p_principal_id uuid, p_actor_id uuid, p_operation text, p_reference text, p_capability text) OWNER TO request_engine_schema_owner;

--
-- Name: assert_arrival_estimate_reservation_confirmed(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.assert_arrival_estimate_reservation_confirmed() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_status text;
BEGIN
    SELECT status INTO v_status
      FROM request_engine.reservations
     WHERE organization_id = NEW.organization_id
       AND id = NEW.reservation_id;
    IF v_status IS NULL THEN
        RAISE EXCEPTION 'arrival estimate reservation must exist' USING ERRCODE = '23514';
    END IF;
    IF v_status <> 'confirmed' THEN
        RAISE EXCEPTION 'arrival estimate requires a confirmed reservation'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$$;


ALTER FUNCTION request_engine.assert_arrival_estimate_reservation_confirmed() OWNER TO request_engine_schema_owner;

--
-- Name: assert_hold_claim_completeness(uuid, uuid); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.assert_hold_claim_completeness(p_org uuid, p_hold uuid) RETURNS void
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_status text;
    v_expires_at timestamptz;
    v_offering_version uuid;
    v_required bigint;
    v_claims bigint;
BEGIN
    SELECT status, expires_at, offering_version_id
      INTO v_status, v_expires_at, v_offering_version
      FROM request_engine.capacity_holds
     WHERE organization_id = p_org
       AND id = p_hold;

    IF NOT FOUND THEN
        RETURN;
    END IF;

    SELECT count(*)
      INTO v_required
      FROM request_engine.offering_resource_requirements
     WHERE organization_id = p_org
       AND offering_version_id = v_offering_version;

    SELECT count(*)
      INTO v_claims
      FROM request_engine.capacity_claims
     WHERE organization_id = p_org
       AND hold_id = p_hold
       AND reservation_id IS NULL
       AND status = 'active';

    IF v_status = 'active' AND v_expires_at > clock_timestamp() THEN
        IF v_required = 0 OR v_claims <> v_required THEN
            RAISE EXCEPTION 'live CapacityHold % requires complete claim set: required %, active %', p_hold, v_required, v_claims
                USING ERRCODE = '23514';
        END IF;
    ELSIF v_status IN ('consumed', 'released', 'expired') AND v_claims <> 0 THEN
        RAISE EXCEPTION 'terminal CapacityHold % cannot retain active hold-only claims', p_hold
            USING ERRCODE = '23514';
    END IF;
END
$$;


ALTER FUNCTION request_engine.assert_hold_claim_completeness(p_org uuid, p_hold uuid) OWNER TO request_engine_schema_owner;

--
-- Name: assert_offered_slot_offer_source_consistency(uuid, uuid); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.assert_offered_slot_offer_source_consistency(p_organization_id uuid, p_slot_offer_id uuid) RETURNS void
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_offer_status text;
    v_offer_expires_at timestamptz;
    v_hold_status text;
    v_hold_expires_at timestamptz;
    v_hold_offering_version_id uuid;
    v_hold_subject_party_id uuid;
    v_hold_location_id uuid;
    v_hold_during tstzrange;
    v_opportunity_status text;
    v_opportunity_offering_version_id uuid;
    v_opportunity_location_id uuid;
    v_opportunity_during tstzrange;
    v_waitlist_status text;
    v_waitlist_subject_party_id uuid;
    v_waitlist_offering_id uuid;
    v_waitlist_location_id uuid;
    v_version_offering_id uuid;
BEGIN
    SELECT so.status,
           so.expires_at,
           h.status,
           h.expires_at,
           h.offering_version_id,
           h.subject_party_id,
           h.location_id,
           h.during,
           o.status,
           o.offering_version_id,
           o.location_id,
           o.during,
           w.status,
           w.subject_party_id,
           w.offering_id,
           w.location_id,
           ov.offering_id
      INTO v_offer_status,
           v_offer_expires_at,
           v_hold_status,
           v_hold_expires_at,
           v_hold_offering_version_id,
           v_hold_subject_party_id,
           v_hold_location_id,
           v_hold_during,
           v_opportunity_status,
           v_opportunity_offering_version_id,
           v_opportunity_location_id,
           v_opportunity_during,
           v_waitlist_status,
           v_waitlist_subject_party_id,
           v_waitlist_offering_id,
           v_waitlist_location_id,
           v_version_offering_id
      FROM request_engine.slot_offers so
      JOIN request_engine.capacity_holds h
        ON h.organization_id = so.organization_id
       AND h.id = so.capacity_hold_id
      JOIN request_engine.slot_opportunities o
        ON o.organization_id = so.organization_id
       AND o.id = so.slot_opportunity_id
      JOIN request_engine.waitlist_entries w
        ON w.organization_id = so.organization_id
       AND w.id = so.waitlist_entry_id
      JOIN request_engine.offering_versions ov
        ON ov.organization_id = o.organization_id
       AND ov.id = o.offering_version_id
     WHERE so.organization_id = p_organization_id
       AND so.id = p_slot_offer_id;

    IF NOT FOUND OR v_offer_status <> 'offered' THEN
        RETURN;
    END IF;

    IF v_opportunity_status <> 'open'
       OR v_waitlist_status <> 'active'
       OR v_hold_status <> 'active'
       OR v_hold_expires_at <= clock_timestamp()
       OR v_offer_expires_at > v_hold_expires_at
       OR v_offer_expires_at > lower(v_opportunity_during)
       OR v_hold_subject_party_id <> v_waitlist_subject_party_id
       OR v_hold_offering_version_id <> v_opportunity_offering_version_id
       OR v_waitlist_offering_id <> v_version_offering_id
       OR v_hold_location_id IS DISTINCT FROM v_opportunity_location_id
       OR (
           v_waitlist_location_id IS NOT NULL
           AND v_waitlist_location_id IS DISTINCT FROM v_opportunity_location_id
       )
       OR v_hold_during <> v_opportunity_during
    THEN
        RAISE EXCEPTION 'offered SlotOffer source state is no longer valid'
            USING ERRCODE = '23514';
    END IF;
END
$$;


ALTER FUNCTION request_engine.assert_offered_slot_offer_source_consistency(p_organization_id uuid, p_slot_offer_id uuid) OWNER TO request_engine_schema_owner;

--
-- Name: assert_organization_has_controller(uuid); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.assert_organization_has_controller(p_organization_id uuid) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
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
                    USING ERRCODE = '55000';
            END IF;
        END
        $$;


ALTER FUNCTION request_engine.assert_organization_has_controller(p_organization_id uuid) OWNER TO request_engine_schema_owner;

--
-- Name: assert_other_tenant_controller(uuid); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.assert_other_tenant_controller(p_excluded_principal_id uuid) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        DECLARE
            v_org_id uuid := request_engine.current_organization_id();
            v_candidate uuid;
        BEGIN
            PERFORM id
              FROM request_engine.staff_memberships
             WHERE organization_id = v_org_id
               AND status = 'active'
             ORDER BY principal_id
             FOR UPDATE;

            SELECT membership.principal_id
              INTO v_candidate
              FROM request_engine.staff_memberships AS membership
             WHERE membership.organization_id = v_org_id
               AND membership.status = 'active'
               AND membership.principal_id <> p_excluded_principal_id
               AND request_engine.principal_is_effective_tenant_controller(
                       v_org_id, membership.principal_id)
             ORDER BY membership.principal_id
             LIMIT 1;
            IF v_candidate IS NULL THEN
                RAISE EXCEPTION 'Tenant must retain an active recovery-capable controller'
                    USING ERRCODE = '23514';
            END IF;
        END
        $$;


ALTER FUNCTION request_engine.assert_other_tenant_controller(p_excluded_principal_id uuid) OWNER TO request_engine_schema_owner;

--
-- Name: assert_reservation_claim_completeness(uuid, uuid); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.assert_reservation_claim_completeness(p_org uuid, p_reservation uuid) RETURNS void
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_status text;
    v_offering_version uuid;
    v_required bigint;
    v_claims bigint;
BEGIN
    SELECT status, offering_version_id
      INTO v_status, v_offering_version
      FROM request_engine.reservations
     WHERE organization_id = p_org
       AND id = p_reservation;

    IF NOT FOUND THEN
        RETURN;
    END IF;

    SELECT count(*)
      INTO v_required
      FROM request_engine.offering_resource_requirements
     WHERE organization_id = p_org
       AND offering_version_id = v_offering_version;

    SELECT count(*)
      INTO v_claims
      FROM request_engine.capacity_claims
     WHERE organization_id = p_org
       AND reservation_id = p_reservation
       AND status = 'active';

    IF v_status = 'confirmed' THEN
        IF v_required = 0 OR v_claims <> v_required THEN
            RAISE EXCEPTION 'confirmed Reservation % requires complete claim set: required %, active %', p_reservation, v_required, v_claims
                USING ERRCODE = '23514';
        END IF;
    ELSIF v_status = 'cancelled' AND v_claims <> 0 THEN
        RAISE EXCEPTION 'cancelled Reservation % cannot retain active capacity claims', p_reservation
            USING ERRCODE = '23514';
    END IF;
END
$$;


ALTER FUNCTION request_engine.assert_reservation_claim_completeness(p_org uuid, p_reservation uuid) OWNER TO request_engine_schema_owner;

--
-- Name: assert_service_queue_coherence(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.assert_service_queue_coherence() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_entry request_engine.queue_entries%ROWTYPE;
    v_session request_engine.service_sessions%ROWTYPE;
    v_entry_id uuid;
BEGIN
    IF TG_TABLE_NAME = 'service_sessions' THEN
        v_entry_id := NEW.queue_entry_id;
    ELSE
        v_entry_id := NEW.id;
    END IF;
    SELECT * INTO v_entry FROM request_engine.queue_entries e
     WHERE e.organization_id = NEW.organization_id AND e.id = v_entry_id;
    SELECT * INTO v_session FROM request_engine.service_sessions s
     WHERE s.organization_id = NEW.organization_id AND s.queue_entry_id = v_entry_id;
    IF v_session.id IS NULL THEN
        IF v_entry.status IN ('serving', 'completed')
           AND v_entry.service_started_at IS NOT NULL THEN
            RAISE EXCEPTION 'QueueEntry % execution requires ServiceSession', v_entry_id
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    IF v_entry.called_at IS NULL OR v_session.started_at < v_entry.called_at THEN
        RAISE EXCEPTION 'ServiceSession % cannot start before QueueEntry is called', v_session.id
            USING ERRCODE = '23514';
    END IF;
    IF v_session.status IN ('active', 'paused') AND v_entry.status <> 'serving' THEN
        RAISE EXCEPTION 'live ServiceSession % requires SERVING QueueEntry', v_session.id
            USING ERRCODE = '23514';
    END IF;
    IF v_session.status = 'completed' AND v_entry.status <> 'completed' THEN
        RAISE EXCEPTION 'completed ServiceSession % requires COMPLETED QueueEntry', v_session.id
            USING ERRCODE = '23514';
    END IF;
    IF v_entry.service_started_at IS DISTINCT FROM v_session.started_at
       OR v_entry.completed_at IS DISTINCT FROM v_session.completed_at THEN
        RAISE EXCEPTION 'QueueEntry compatibility timestamps must equal ServiceSession timestamps'
            USING ERRCODE = '23514';
    END IF;
    IF v_entry.status = 'no_show' THEN
        RAISE EXCEPTION 'NO_SHOW QueueEntry cannot have a ServiceSession' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$$;


ALTER FUNCTION request_engine.assert_service_queue_coherence() OWNER TO request_engine_schema_owner;

--
-- Name: assert_session_interruption_coherence(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.assert_session_interruption_coherence() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_session_id uuid;
    v_status text;
    v_started_at timestamptz;
    v_completed_at timestamptz;
    v_open bigint;
BEGIN
    IF TG_TABLE_NAME = 'service_sessions' THEN
        v_session_id := NEW.id;
    ELSE
        v_session_id := NEW.service_session_id;
    END IF;
    SELECT status, started_at, completed_at
      INTO v_status, v_started_at, v_completed_at
      FROM request_engine.service_sessions
     WHERE organization_id = NEW.organization_id AND id = v_session_id;
    IF NOT FOUND THEN RETURN NEW; END IF;

    IF EXISTS (
        SELECT 1 FROM request_engine.service_session_interruptions i
         WHERE i.organization_id = NEW.organization_id
           AND i.service_session_id = v_session_id
           AND i.started_at < v_started_at
    ) THEN
        RAISE EXCEPTION 'ServiceSession % interruption cannot predate execution', v_session_id
            USING ERRCODE = '23514';
    END IF;
    IF v_completed_at IS NOT NULL AND EXISTS (
        SELECT 1 FROM request_engine.service_session_interruptions i
         WHERE i.organization_id = NEW.organization_id
           AND i.service_session_id = v_session_id
           AND (i.ended_at IS NULL OR i.ended_at > v_completed_at)
    ) THEN
        RAISE EXCEPTION 'ServiceSession % interruption cannot outlive execution', v_session_id
            USING ERRCODE = '23514';
    END IF;

    SELECT count(*) INTO v_open FROM request_engine.service_session_interruptions
     WHERE organization_id = NEW.organization_id
       AND service_session_id = v_session_id AND ended_at IS NULL;
    IF (v_status = 'paused' AND v_open <> 1) OR (v_status <> 'paused' AND v_open <> 0) THEN
        RAISE EXCEPTION 'ServiceSession % interruption state is incoherent', v_session_id
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$$;


ALTER FUNCTION request_engine.assert_session_interruption_coherence() OWNER TO request_engine_schema_owner;

--
-- Name: assert_slot_offer_consistency(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.assert_slot_offer_consistency() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
DECLARE
    offer_row request_engine.slot_offers%ROWTYPE;
    hold_row request_engine.capacity_holds%ROWTYPE;
    opportunity_row request_engine.slot_opportunities%ROWTYPE;
    waitlist_row request_engine.waitlist_entries%ROWTYPE;
    opportunity_offering_id uuid;
    expected_hold_status text;
    v_claim_count bigint;
    v_promoted_claim_count bigint;
    v_reservation_count bigint;
    v_reservation_id uuid;
    v_reservation_status text;
BEGIN
    IF TG_TABLE_NAME = 'slot_offers' THEN
        offer_row := NEW;
    ELSE
        SELECT so.*
          INTO offer_row
          FROM request_engine.slot_offers so
         WHERE so.organization_id = NEW.organization_id
           AND so.capacity_hold_id = NEW.id;

        IF NOT FOUND THEN
            RETURN NEW;
        END IF;
    END IF;

    SELECT h.*
      INTO STRICT hold_row
      FROM request_engine.capacity_holds h
     WHERE h.organization_id = offer_row.organization_id
       AND h.id = offer_row.capacity_hold_id;

    SELECT o.*
      INTO STRICT opportunity_row
      FROM request_engine.slot_opportunities o
     WHERE o.organization_id = offer_row.organization_id
       AND o.id = offer_row.slot_opportunity_id;

    SELECT ov.offering_id
      INTO STRICT opportunity_offering_id
      FROM request_engine.offering_versions ov
     WHERE ov.organization_id = opportunity_row.organization_id
       AND ov.id = opportunity_row.offering_version_id;

    SELECT w.*
      INTO STRICT waitlist_row
      FROM request_engine.waitlist_entries w
     WHERE w.organization_id = offer_row.organization_id
       AND w.id = offer_row.waitlist_entry_id;

    IF waitlist_row.offering_id <> opportunity_offering_id THEN
        RAISE EXCEPTION 'SlotOffer % candidate does not match Opportunity Offering',
            offer_row.id USING ERRCODE = '23514';
    END IF;

    IF hold_row.subject_party_id <> waitlist_row.subject_party_id THEN
        RAISE EXCEPTION 'SlotOffer provenance mismatch: Hold subject does not match WaitlistEntry subject'
            USING ERRCODE = '23514';
    END IF;

    IF hold_row.offering_version_id <> opportunity_row.offering_version_id
       OR hold_row.location_id IS DISTINCT FROM opportunity_row.location_id
       OR hold_row.during <> opportunity_row.during THEN
        RAISE EXCEPTION 'SlotOffer % Hold does not cover its SlotOpportunity',
            offer_row.id USING ERRCODE = '23514';
    END IF;

    IF offer_row.expires_at > hold_row.expires_at
       OR offer_row.expires_at > lower(opportunity_row.during) THEN
        RAISE EXCEPTION 'SlotOffer % cannot outlive its CapacityHold or SlotOpportunity start',
            offer_row.id USING ERRCODE = '23514';
    END IF;

    expected_hold_status := CASE offer_row.status
        WHEN 'offered' THEN 'active'
        WHEN 'accepted' THEN 'consumed'
        WHEN 'declined' THEN 'released'
        WHEN 'cancelled' THEN 'released'
        WHEN 'expired' THEN 'expired'
        ELSE NULL
    END;

    IF expected_hold_status IS NULL OR hold_row.status <> expected_hold_status THEN
        RAISE EXCEPTION 'SlotOffer % status % requires Hold status %, found %',
            offer_row.id, offer_row.status, expected_hold_status, hold_row.status
            USING ERRCODE = '23514';
    END IF;

    IF offer_row.status = 'accepted' THEN
        IF opportunity_row.status <> 'filled' OR waitlist_row.status <> 'fulfilled' THEN
            RAISE EXCEPTION 'accepted SlotOffer % requires filled Opportunity and fulfilled WaitlistEntry',
                offer_row.id USING ERRCODE = '23514';
        END IF;

        SELECT count(*),
               count(*) FILTER (
                   WHERE c.status = 'active' AND c.reservation_id IS NOT NULL
               ),
               count(DISTINCT c.reservation_id) FILTER (
                   WHERE c.status = 'active' AND c.reservation_id IS NOT NULL
               )
          INTO v_claim_count,
               v_promoted_claim_count,
               v_reservation_count
          FROM request_engine.capacity_claims c
         WHERE c.organization_id = offer_row.organization_id
           AND c.hold_id = offer_row.capacity_hold_id;

        SELECT c.reservation_id
          INTO v_reservation_id
          FROM request_engine.capacity_claims c
         WHERE c.organization_id = offer_row.organization_id
           AND c.hold_id = offer_row.capacity_hold_id
           AND c.status = 'active'
           AND c.reservation_id IS NOT NULL
         LIMIT 1;

        IF v_claim_count = 0
           OR v_promoted_claim_count <> v_claim_count
           OR v_reservation_count <> 1
           OR v_reservation_id IS NULL THEN
            RAISE EXCEPTION 'accepted SlotOffer % requires complete Hold-to-Reservation claim promotion',
                offer_row.id USING ERRCODE = '23514';
        END IF;

        SELECT r.status
          INTO v_reservation_status
          FROM request_engine.reservations r
         WHERE r.organization_id = offer_row.organization_id
           AND r.id = v_reservation_id;

        IF NOT FOUND OR v_reservation_status <> 'confirmed' THEN
            RAISE EXCEPTION 'accepted SlotOffer % requires a confirmed Reservation',
                offer_row.id USING ERRCODE = '23514';
        END IF;
    END IF;

    RETURN NEW;
END
$$;


ALTER FUNCTION request_engine.assert_slot_offer_consistency() OWNER TO request_engine_schema_owner;

--
-- Name: assert_staff_manager(text); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.assert_staff_manager(p_capability text) RETURNS uuid
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        DECLARE
            v_actor_id uuid;
            v_org_id uuid;
        BEGIN
            BEGIN
                v_actor_id := current_setting(
                    'request_engine.authenticated_principal_id', true
                )::uuid;
                v_org_id := request_engine.current_organization_id();
            EXCEPTION WHEN invalid_text_representation THEN
                RAISE EXCEPTION 'Tenant actor provenance is malformed'
                    USING ERRCODE = '28000';
            END;
            IF v_actor_id IS NULL OR v_org_id IS NULL THEN
                RAISE EXCEPTION 'Tenant actor provenance is required'
                    USING ERRCODE = '28000';
            END IF;
            PERFORM 1
              FROM request_engine.principals AS principal
              JOIN request_engine.staff_memberships AS membership
                ON membership.principal_id = principal.id
               AND membership.organization_id = v_org_id
               AND membership.status = 'active'
              JOIN request_engine.principal_authority_grants AS grant_row
                ON grant_row.principal_id = principal.id
               AND grant_row.organization_id = v_org_id
               AND grant_row.capability_key = p_capability
               AND grant_row.status = 'active'
             WHERE principal.id = v_actor_id
               AND principal.organization_id = v_org_id
               AND principal.principal_plane = 'tenant'
               AND principal.principal_kind = 'human'
               AND principal.active
             FOR SHARE OF principal, membership, grant_row;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Current Principal lacks active staff authority'
                    USING ERRCODE = '42501';
            END IF;
            RETURN v_actor_id;
        END
        $$;


ALTER FUNCTION request_engine.assert_staff_manager(p_capability text) OWNER TO request_engine_schema_owner;

--
-- Name: assert_tenant_has_controller(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.assert_tenant_has_controller() RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        DECLARE
            v_org_id uuid := request_engine.current_organization_id();
            v_candidate uuid;
        BEGIN
            SELECT membership.principal_id
              INTO v_candidate
              FROM request_engine.staff_memberships AS membership
             WHERE membership.organization_id = v_org_id
               AND membership.status = 'active'
               AND request_engine.principal_is_effective_tenant_controller(
                       v_org_id, membership.principal_id)
             ORDER BY membership.principal_id
             LIMIT 1;
            IF v_candidate IS NULL THEN
                RAISE EXCEPTION 'Tenant must retain an active recovery-capable controller'
                    USING ERRCODE = '23514';
            END IF;
        END
        $$;


ALTER FUNCTION request_engine.assert_tenant_has_controller() OWNER TO request_engine_schema_owner;

--
-- Name: attach_shared_capacity_claim_link(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.attach_shared_capacity_claim_link() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_shared_capacity_identity_id uuid;
BEGIN
    IF NEW.status <> 'active' THEN
        RETURN NEW;
    END IF;

    SELECT b.shared_capacity_identity_id
      INTO v_shared_capacity_identity_id
      FROM request_engine.shared_capacity_bindings b
     WHERE b.organization_id = NEW.organization_id
       AND b.resource_id = NEW.resource_id
       AND b.status = 'active';

    IF v_shared_capacity_identity_id IS NOT NULL THEN
        INSERT INTO request_engine.shared_capacity_claim_links (
            capacity_claim_id, shared_capacity_identity_id
        ) VALUES (
            NEW.id, v_shared_capacity_identity_id
        )
        ON CONFLICT (capacity_claim_id) DO NOTHING;
    END IF;
    RETURN NEW;
END
$$;


ALTER FUNCTION request_engine.attach_shared_capacity_claim_link() OWNER TO request_engine_schema_owner;

--
-- Name: bind_consumed_identity_candidate_v1(uuid, uuid, text[], uuid); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.bind_consumed_identity_candidate_v1(p_candidate_id uuid, p_party_id uuid, p_consent_fields text[], p_principal_id uuid) RETURNS uuid
