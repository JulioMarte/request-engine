CREATE FUNCTION request_auth.finalize_webauthn_registration(p_challenge_digest bytea, p_credential_row_id uuid, p_credential_id_bytes bytea, p_public_key bytea, p_sign_count bigint, p_aaguid text, p_backup_eligible boolean, p_backup_state boolean, p_user_verified boolean) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $_$
        DECLARE
            v_challenge request_engine.webauthn_challenges%ROWTYPE;
            v_identity_status text;
        BEGIN
            IF p_challenge_digest IS NULL
               OR octet_length(p_challenge_digest) <> 32
               OR p_credential_row_id IS NULL
               OR p_credential_id_bytes IS NULL
               OR octet_length(p_credential_id_bytes) NOT BETWEEN 16 AND 1023
               OR p_public_key IS NULL
               OR octet_length(p_public_key) = 0
               OR p_sign_count < 0
               OR p_aaguid IS NULL
               OR p_aaguid !~ '^[0-9a-f]{32}$'
            THEN
                RETURN false;
            END IF;

            SELECT challenge.* INTO v_challenge
              FROM request_engine.webauthn_challenges AS challenge
             WHERE challenge.challenge_digest = p_challenge_digest
               AND challenge.purpose = 'registration'
               AND challenge.status = 'pending'
               AND challenge.expires_at > clock_timestamp()
             FOR UPDATE;
            IF NOT FOUND OR v_challenge.native_identity_id IS NULL
               OR v_challenge.user_handle IS NULL THEN
                RETURN false;
            END IF;

            -- A suspended native authority must not accept new credentials.
            PERFORM 1
              FROM request_engine.identity_authorities AS authority
              JOIN request_engine.native_identities AS native_identity
                ON native_identity.identity_authority_id = authority.id
             WHERE native_identity.id = v_challenge.native_identity_id
               AND authority.kind = 'native' AND authority.status = 'active'
             FOR SHARE OF authority;
            IF NOT FOUND THEN RETURN false; END IF;

            SELECT identity.status INTO v_identity_status
              FROM request_engine.native_identities AS identity
             WHERE identity.id = v_challenge.native_identity_id
             FOR UPDATE;
            IF NOT FOUND OR v_identity_status <> 'active' THEN
                RETURN false;
            END IF;

            IF v_challenge.expires_at <= clock_timestamp() THEN RETURN false; END IF;

            BEGIN
            INSERT INTO request_engine.webauthn_credentials (
                id, native_identity_id, credential_id, public_key, sign_count,
                aaguid, backup_eligible, backup_state, user_verified, user_handle
            ) VALUES (
                p_credential_row_id, v_challenge.native_identity_id,
                p_credential_id_bytes, p_public_key, p_sign_count, p_aaguid,
                p_backup_eligible, p_backup_state, p_user_verified, v_challenge.user_handle
            )
            ON CONFLICT (credential_id) DO NOTHING;
            IF NOT FOUND THEN
                RETURN false;
            END IF;

            IF v_challenge.expires_at <= clock_timestamp() THEN
                    RAISE EXCEPTION 'WebAuthn finalization deadline elapsed'
                        USING ERRCODE='PWE01';
                END IF;

            UPDATE request_engine.webauthn_challenges
               SET status = 'consumed', consumed_at = clock_timestamp()
             WHERE id = v_challenge.id;
            RETURN true;
            EXCEPTION WHEN SQLSTATE 'PWE01' THEN
                RETURN false;
            END;
        END
        $_$;


ALTER FUNCTION request_auth.finalize_webauthn_registration(p_challenge_digest bytea, p_credential_row_id uuid, p_credential_id_bytes bytea, p_public_key bytea, p_sign_count bigint, p_aaguid text, p_backup_eligible boolean, p_backup_state boolean, p_user_verified boolean) OWNER TO request_engine_schema_owner;

--
-- Name: finalize_webauthn_step_up(bytea, uuid, uuid, uuid, bigint, boolean, boolean); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.finalize_webauthn_step_up(p_challenge_digest bytea, p_credential_row_id uuid, p_session_id uuid, p_native_identity_id uuid, p_sign_count bigint, p_backup_eligible boolean, p_user_verified boolean) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
        DECLARE
            v_challenge request_engine.webauthn_challenges%ROWTYPE;
            v_session request_engine.native_sessions%ROWTYPE;
            v_credential_status text;
            v_identity_status text;
            v_identity_epoch bigint;
            v_methods text[];
            v_user_verified boolean;
        BEGIN
            IF p_challenge_digest IS NULL
               OR octet_length(p_challenge_digest) <> 32
               OR p_credential_row_id IS NULL
               OR p_session_id IS NULL
               OR p_native_identity_id IS NULL
               OR p_sign_count < 0
            THEN
                RETURN false;
            END IF;

            SELECT challenge.* INTO v_challenge
              FROM request_engine.webauthn_challenges AS challenge
             WHERE challenge.challenge_digest = p_challenge_digest
               AND challenge.purpose = 'step_up'
               AND challenge.status = 'pending'
               AND challenge.expires_at > clock_timestamp()
             FOR UPDATE;
            IF NOT FOUND OR v_challenge.session_id IS DISTINCT FROM p_session_id THEN
                RETURN false;
            END IF;

            -- Canonical lock order: authority -> identity -> credential -> session.
            PERFORM 1
              FROM request_engine.identity_authorities AS authority
              JOIN request_engine.native_identities AS native_identity
                ON native_identity.identity_authority_id = authority.id
             WHERE native_identity.id = p_native_identity_id
               AND authority.kind = 'native' AND authority.status = 'active'
             FOR SHARE OF authority;
            IF NOT FOUND THEN RETURN false; END IF;

            SELECT identity.status, identity.session_epoch
              INTO v_identity_status, v_identity_epoch
              FROM request_engine.native_identities AS identity
             WHERE identity.id = p_native_identity_id
             FOR SHARE;
            IF NOT FOUND OR v_identity_status <> 'active' THEN
                RETURN false;
            END IF;

            SELECT status INTO v_credential_status
              FROM request_engine.webauthn_credentials
             WHERE id = p_credential_row_id
               AND native_identity_id = p_native_identity_id
             FOR UPDATE;
            IF NOT FOUND OR v_credential_status <> 'active' THEN
                RETURN false;
            END IF;

            SELECT session.* INTO v_session
              FROM request_engine.native_sessions AS session
             WHERE session.id = p_session_id
             FOR UPDATE;
            IF NOT FOUND
               OR v_session.native_identity_id <> p_native_identity_id
               OR v_session.status <> 'active'
               OR v_session.expires_at <= clock_timestamp()
               OR v_session.session_epoch <> v_identity_epoch
            THEN
                RETURN false;
            END IF;

            IF v_challenge.expires_at <= clock_timestamp() OR v_session.expires_at <= clock_timestamp() THEN RETURN false; END IF;

            BEGIN
            UPDATE request_engine.webauthn_credentials
               SET sign_count = GREATEST(sign_count, p_sign_count),
                   last_used_at = clock_timestamp(),
                   user_verified = user_verified OR p_user_verified,
                   last_regression_at = CASE
                       WHEN NOT p_backup_eligible
                            AND p_sign_count > 0
                            AND sign_count > 0
                            AND p_sign_count < sign_count
                       THEN clock_timestamp()
                       ELSE last_regression_at
                   END
             WHERE id = p_credential_row_id;

            v_methods := CASE
                WHEN 'webauthn' = ANY(v_session.authentication_methods)
                    THEN v_session.authentication_methods
                ELSE v_session.authentication_methods || ARRAY['webauthn']::text[]
            END;
            v_user_verified := v_session.user_verified OR p_user_verified;

            UPDATE request_engine.native_sessions
               SET authentication_methods = v_methods,
                   authentication_assurance = request_engine.derive_authentication_assurance(
                       v_methods, v_user_verified, v_session.recovery_derived
                   ),
                   user_verified = v_user_verified,
                   last_authenticated_at = clock_timestamp(),
                   last_seen_at = clock_timestamp()
             WHERE id = p_session_id;

            IF v_challenge.expires_at <= clock_timestamp() OR v_session.expires_at <= clock_timestamp() THEN
                    RAISE EXCEPTION 'WebAuthn finalization deadline elapsed'
                        USING ERRCODE='PWE01';
                END IF;

            UPDATE request_engine.webauthn_challenges
               SET status = 'consumed', consumed_at = clock_timestamp()
             WHERE id = v_challenge.id;
            RETURN true;
            EXCEPTION WHEN SQLSTATE 'PWE01' THEN
                RETURN false;
            END;
        END
        $$;


ALTER FUNCTION request_auth.finalize_webauthn_step_up(p_challenge_digest bytea, p_credential_row_id uuid, p_session_id uuid, p_native_identity_id uuid, p_sign_count bigint, p_backup_eligible boolean, p_user_verified boolean) OWNER TO request_engine_schema_owner;

--
-- Name: is_native_authority_ready(uuid); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.is_native_authority_ready(p_authority_id uuid) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
            SELECT EXISTS (
                SELECT 1 FROM request_engine.identity_authorities
                 WHERE id = p_authority_id AND kind = 'native' AND status = 'active'
            )
        $$;


ALTER FUNCTION request_auth.is_native_authority_ready(p_authority_id uuid) OWNER TO request_engine_schema_owner;

--
-- Name: lock_accepted_native_credential(uuid, uuid); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.lock_accepted_native_credential(p_credential uuid, p_expected_authority uuid) RETURNS uuid
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
    DECLARE identity_id uuid; authority_id uuid;
    BEGIN
        SELECT c.native_identity_id INTO identity_id FROM (
            SELECT id,native_identity_id FROM request_engine.native_credentials
            WHERE id=p_credential AND kind='password'
            UNION ALL
            SELECT id,native_identity_id FROM request_engine.webauthn_credentials
            WHERE id=p_credential
        ) c;
        IF identity_id IS NULL THEN RETURN NULL; END IF;
        SELECT i.identity_authority_id INTO authority_id
            FROM request_engine.native_identities i WHERE i.id=identity_id;
        IF authority_id IS DISTINCT FROM p_expected_authority THEN RETURN NULL; END IF;
        PERFORM 1 FROM request_engine.identity_authorities a
            WHERE a.id=authority_id AND a.kind='native' AND a.status='active' FOR SHARE;
        IF NOT FOUND THEN RETURN NULL; END IF;
        PERFORM 1 FROM request_engine.native_identities i
            WHERE i.id=identity_id AND i.status='active' FOR SHARE;
        IF NOT FOUND THEN RETURN NULL; END IF;
        -- Credential mutation/recovery follows authority -> identity -> credential.
        PERFORM 1 FROM request_engine.native_credentials c
            WHERE c.id=p_credential AND c.native_identity_id=identity_id
              AND c.kind='password' AND c.status='active' FOR SHARE;
        IF NOT FOUND THEN
            PERFORM 1 FROM request_engine.webauthn_credentials c
                WHERE c.id=p_credential AND c.native_identity_id=identity_id
                  AND c.status='active' FOR SHARE;
            IF NOT FOUND THEN RETURN NULL; END IF;
        END IF;
        IF EXISTS(SELECT 1 FROM request_engine.native_identity_recovery_state r
            WHERE r.native_identity_id=identity_id AND r.state='recovery_restricted') THEN
            RETURN NULL;
        END IF;
        RETURN identity_id;
    END $$;


ALTER FUNCTION request_auth.lock_accepted_native_credential(p_credential uuid, p_expected_authority uuid) OWNER TO request_engine_schema_owner;

--
-- Name: lock_accepted_native_session(uuid, uuid); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.lock_accepted_native_session(p_session uuid, p_expected_authority uuid) RETURNS uuid
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
    DECLARE snapshot request_engine.native_sessions%ROWTYPE;
            identity_id uuid; current_epoch bigint;
    BEGIN
        -- Read immutable provenance first; retain canonical authenticator lock order.
        SELECT * INTO snapshot FROM request_engine.native_sessions WHERE id=p_session;
        IF NOT FOUND THEN RETURN NULL; END IF;
        identity_id := request_auth.lock_accepted_native_credential(
            coalesce(snapshot.password_credential_id,snapshot.webauthn_credential_id),
            p_expected_authority);
        IF identity_id IS NULL OR identity_id<>snapshot.native_identity_id THEN
            RETURN NULL;
        END IF;
        SELECT session_epoch INTO current_epoch FROM request_engine.native_identities
            WHERE id=identity_id;
        -- Logout locks only this row; global revocation holds identity before session.
        SELECT * INTO snapshot FROM request_engine.native_sessions
            WHERE id=p_session FOR SHARE;
        IF NOT FOUND OR snapshot.status<>'active'
            OR snapshot.expires_at<=clock_timestamp()
            OR snapshot.session_epoch<>current_epoch OR snapshot.recovery_derived
            OR snapshot.authentication_assurance='recovery'
            OR 'recovery_code'=ANY(snapshot.authentication_methods)
            OR (snapshot.password_credential_id IS NOT NULL
                AND NOT ('password'=ANY(snapshot.authentication_methods)))
            OR (snapshot.webauthn_credential_id IS NOT NULL
                AND NOT ('webauthn'=ANY(snapshot.authentication_methods))) THEN
            RETURN NULL;
        END IF;
        RETURN identity_id;
    END $$;


ALTER FUNCTION request_auth.lock_accepted_native_session(p_session uuid, p_expected_authority uuid) OWNER TO request_engine_schema_owner;

--
-- Name: lock_credentialed_native_identity(uuid, uuid); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.lock_credentialed_native_identity(p_identity_authority_id uuid, p_native_identity_id uuid) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
        BEGIN
            PERFORM 1 FROM request_engine.identity_authorities
             WHERE id = p_identity_authority_id
               AND kind = 'native' AND status = 'active'
             FOR SHARE;
            IF NOT FOUND THEN RETURN false; END IF;

            PERFORM 1
              FROM request_engine.native_identities AS native_identity
             WHERE native_identity.id = p_native_identity_id
               AND native_identity.identity_authority_id = p_identity_authority_id
               AND native_identity.status = 'active'
             FOR SHARE OF native_identity;
            IF NOT FOUND THEN RETURN false; END IF;

            PERFORM 1 FROM request_engine.native_credentials AS credential
             WHERE credential.native_identity_id = p_native_identity_id
               AND credential.kind = 'password' AND credential.status = 'active'
             FOR SHARE OF credential;
            RETURN FOUND;
        END
        $$;


ALTER FUNCTION request_auth.lock_credentialed_native_identity(p_identity_authority_id uuid, p_native_identity_id uuid) OWNER TO request_engine_schema_owner;

--
-- Name: lock_native_identity_recovery_postures(uuid[]); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.lock_native_identity_recovery_postures(p_native_identity_ids uuid[]) RETURNS TABLE(native_identity_id uuid, identity_authority_id uuid, identity_status text, recovery_state text, recovery_epoch bigint)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
        DECLARE v_requested_count integer;
                v_identity_count integer;
        BEGIN
            IF p_native_identity_ids IS NULL OR cardinality(p_native_identity_ids)<1
               OR cardinality(p_native_identity_ids)>2
               OR array_position(p_native_identity_ids,NULL) IS NOT NULL
            THEN RAISE EXCEPTION 'Invalid native identity lock set' USING ERRCODE='22023'; END IF;
            SELECT count(DISTINCT id)::integer INTO v_requested_count
              FROM unnest(p_native_identity_ids) AS requested(id);

            -- Canonical account lock order: active native authority UUID, then
            -- native identity UUID, then recovery-state UUID. Recovery writers use
            -- authority -> identity -> posture too; completion uses authority -> posture.
            PERFORM authority.id
              FROM request_engine.identity_authorities authority
              JOIN request_engine.native_identities identity
                ON identity.identity_authority_id=authority.id
             WHERE identity.id=ANY(p_native_identity_ids)
               AND authority.kind='native' AND authority.status='active'
             ORDER BY authority.id FOR SHARE OF authority;

            PERFORM identity.id
              FROM request_engine.native_identities identity
              JOIN request_engine.identity_authorities authority
                ON authority.id=identity.identity_authority_id
             WHERE identity.id=ANY(p_native_identity_ids)
               AND authority.kind='native' AND authority.status='active'
             ORDER BY identity.id FOR UPDATE OF identity;
            GET DIAGNOSTICS v_identity_count=ROW_COUNT;
            IF v_identity_count<>v_requested_count THEN RETURN; END IF;

            PERFORM recovery.native_identity_id
              FROM request_engine.native_identity_recovery_state recovery
             WHERE recovery.native_identity_id=ANY(p_native_identity_ids)
             ORDER BY recovery.native_identity_id FOR SHARE OF recovery;

            RETURN QUERY
            SELECT identity.id,authority.id,identity.status,
                   coalesce(recovery.state,'normal'),coalesce(recovery.recovery_epoch,0)
              FROM request_engine.native_identities identity
              JOIN request_engine.identity_authorities authority
                ON authority.id=identity.identity_authority_id
              LEFT JOIN request_engine.native_identity_recovery_state recovery
                ON recovery.native_identity_id=identity.id
             WHERE identity.id=ANY(p_native_identity_ids)
               AND authority.kind='native' AND authority.status='active'
             ORDER BY identity.id;
        END $$;


ALTER FUNCTION request_auth.lock_native_identity_recovery_postures(p_native_identity_ids uuid[]) OWNER TO request_engine_schema_owner;

--
-- Name: prepare_native_recovery_address(uuid, uuid, text, text, uuid, bytea, text, timestamp with time zone); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.prepare_native_recovery_address(p_address_id uuid, p_native_identity_id uuid, p_kind text, p_normalized_address text, p_verification_id uuid, p_token_digest bytea, p_token_fingerprint text, p_expires_at timestamp with time zone) RETURNS TABLE(recovery_address_id uuid, address_status text, verification_created boolean)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $_$
        DECLARE
            v_identity_status text;
            v_existing record;
            v_address_id uuid;
        BEGIN
            IF p_address_id IS NULL
               OR p_native_identity_id IS NULL
               OR p_kind <> 'email'
               OR p_normalized_address IS NULL
               OR length(p_normalized_address) NOT BETWEEN 3 AND 320
               OR p_normalized_address !~ '^[^[:space:]@]+@[^[:space:]@]+$'
               OR p_verification_id IS NULL
               OR p_token_digest IS NULL
               OR octet_length(p_token_digest) <> 32
               OR p_token_fingerprint !~ '^[0-9a-f]{16}$'
               OR p_expires_at IS NULL
               OR p_expires_at <= clock_timestamp()
               OR p_expires_at > clock_timestamp() + interval '30 minutes'
            THEN
                RETURN;
            END IF;

            SELECT identity.status
              INTO v_identity_status
              FROM request_engine.native_identities AS identity
             WHERE identity.id = p_native_identity_id
             FOR UPDATE;
            IF NOT FOUND OR v_identity_status <> 'active' THEN
                RETURN;
            END IF;

            SELECT address.id, address.status
              INTO v_existing
              FROM request_engine.native_recovery_addresses AS address
             WHERE address.native_identity_id = p_native_identity_id
               AND address.kind = p_kind
               AND address.normalized_address = p_normalized_address
               AND address.status <> 'revoked'
             FOR UPDATE;

            IF FOUND AND v_existing.status = 'verified' THEN
                RETURN QUERY SELECT v_existing.id, 'verified'::text, false;
                RETURN;
            END IF;

            IF FOUND THEN
                v_address_id := v_existing.id;
                UPDATE request_engine.native_recovery_address_verifications
                   SET status = 'revoked',
                       revoked_at = clock_timestamp()
                 WHERE recovery_address_id = v_address_id
                   AND status = 'pending';
            ELSE
                v_address_id := p_address_id;
                INSERT INTO request_engine.native_recovery_addresses (
                    id, native_identity_id, kind, normalized_address
                ) VALUES (
                    v_address_id,
                    p_native_identity_id,
                    p_kind,
                    p_normalized_address
                );
            END IF;

            INSERT INTO request_engine.native_recovery_address_verifications (
                id,
                recovery_address_id,
                token_digest,
                token_fingerprint,
                expires_at
            ) VALUES (
                p_verification_id,
                v_address_id,
                p_token_digest,
                p_token_fingerprint,
                p_expires_at
            );

            INSERT INTO request_engine.native_recovery_address_facts (
                native_identity_id,
                recovery_address_id,
                event_kind,
                correlation_id
            ) VALUES (
                p_native_identity_id,
                v_address_id,
                'verification_requested',
                NULLIF(current_setting('request_engine.correlation_id', true), '')::uuid
            );

            RETURN QUERY SELECT v_address_id, 'pending'::text, true;
        END
        $_$;


ALTER FUNCTION request_auth.prepare_native_recovery_address(p_address_id uuid, p_native_identity_id uuid, p_kind text, p_normalized_address text, p_verification_id uuid, p_token_digest bytea, p_token_fingerprint text, p_expires_at timestamp with time zone) OWNER TO request_engine_schema_owner;

--
-- Name: promote_recovery_code_set(uuid, uuid); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.promote_recovery_code_set(p_set_id uuid, p_native_identity_id uuid) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
        DECLARE
            v_set request_engine.recovery_code_sets%ROWTYPE;
            v_identity_status text;
        BEGIN
            IF p_set_id IS NULL OR p_native_identity_id IS NULL THEN
                RETURN false;
            END IF;

            SELECT identity.status INTO v_identity_status
              FROM request_engine.native_identities AS identity
             WHERE identity.id = p_native_identity_id
             FOR UPDATE;
            IF NOT FOUND OR v_identity_status <> 'active' THEN
                RETURN false;
            END IF;

            SELECT code_set.* INTO v_set
              FROM request_engine.recovery_code_sets AS code_set
             WHERE code_set.id = p_set_id
             FOR UPDATE;
            IF NOT FOUND
               OR v_set.status <> 'active'
               OR v_set.setup_session_id IS NULL
            THEN
                RETURN false;
            END IF;

            UPDATE request_engine.recovery_code_sets
               SET setup_session_id = NULL,
                   native_identity_id = p_native_identity_id
             WHERE id = p_set_id;

            INSERT INTO request_engine.platform_recovery_code_facts (
                event_kind, set_id, native_identity_id, setup_session_id,
                actor_principal_id, actor_authentication_method, capability_key,
                correlation_id
            ) VALUES (
                'set_promoted', p_set_id, p_native_identity_id, v_set.setup_session_id,
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


ALTER FUNCTION request_auth.promote_recovery_code_set(p_set_id uuid, p_native_identity_id uuid) OWNER TO request_engine_schema_owner;

--
-- Name: queue_native_verified_recovery(uuid, text, uuid); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.queue_native_verified_recovery(p_identity_authority_id uuid, p_login_handle text, p_request_id uuid) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
        DECLARE
            v_identity_id uuid;
            v_address record;
        BEGIN
            IF p_identity_authority_id IS NULL
               OR p_login_handle IS NULL
               OR length(p_login_handle) NOT BETWEEN 1 AND 320
               OR p_request_id IS NULL
            THEN
                RETURN false;
            END IF;

            PERFORM 1
              FROM request_engine.identity_authorities AS authority
             WHERE authority.id = p_identity_authority_id
               AND authority.kind = 'native'
               AND authority.status = 'active'
             FOR SHARE;
            IF NOT FOUND THEN
                RETURN false;
            END IF;

            SELECT identity.id
              INTO v_identity_id
              FROM request_engine.native_identities AS identity
             WHERE identity.identity_authority_id = p_identity_authority_id
               AND identity.login_handle = p_login_handle
               AND identity.status = 'active'
             FOR UPDATE;
            IF NOT FOUND THEN
                RETURN false;
            END IF;

            SELECT address.id, address.normalized_address
              INTO v_address
              FROM request_engine.native_recovery_addresses AS address
             WHERE address.native_identity_id = v_identity_id
               AND address.kind = 'email'
               AND address.status = 'verified'
             ORDER BY address.verified_at DESC, address.id
             LIMIT 1
             FOR SHARE;
            IF NOT FOUND THEN
                RETURN false;
            END IF;

            UPDATE request_engine.native_recovery_delivery_requests AS request
               SET status = 'cancelled',
                   updated_at = clock_timestamp(),
                   last_error_class = 'request_expired'
             WHERE request.native_identity_id = v_identity_id
               AND request.status = 'pending'
               AND request.request_expires_at <= clock_timestamp();

            IF EXISTS (
                SELECT 1
                  FROM request_engine.native_recovery_delivery_requests AS request
                 WHERE request.native_identity_id = v_identity_id
                   AND request.status IN ('pending', 'sending')
            ) THEN
                RETURN false;
            END IF;

            IF EXISTS (
                SELECT 1
                  FROM request_engine.native_recovery_address_facts AS fact
                 WHERE fact.native_identity_id = v_identity_id
                   AND fact.recovery_address_id = v_address.id
                   AND fact.event_kind = 'recovery_requested'
                   AND fact.created_at > clock_timestamp() - interval '1 minute'
            ) THEN
                RETURN false;
            END IF;

            INSERT INTO request_engine.native_recovery_delivery_requests (
                id,
                native_identity_id,
                recovery_address_id,
                destination_reference,
                request_expires_at
            ) VALUES (
                p_request_id,
                v_identity_id,
                v_address.id,
                v_address.normalized_address,
                clock_timestamp() + interval '30 minutes'
            );

            INSERT INTO request_engine.native_recovery_address_facts (
                native_identity_id,
                recovery_address_id,
                event_kind,
                correlation_id
            ) VALUES (
                v_identity_id,
                v_address.id,
                'recovery_requested',
                NULLIF(current_setting('request_engine.correlation_id', true), '')::uuid
            );
            RETURN true;
        END
        $$;


ALTER FUNCTION request_auth.queue_native_verified_recovery(p_identity_authority_id uuid, p_login_handle text, p_request_id uuid) OWNER TO request_engine_schema_owner;

--
-- Name: read_active_webauthn_identity(uuid, text); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.read_active_webauthn_identity(p_identity_authority_id uuid, p_login_handle text) RETURNS uuid
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
            SELECT native_identity.id
              FROM request_engine.native_identities AS native_identity
              JOIN request_engine.identity_authorities AS authority
                ON authority.id = native_identity.identity_authority_id
             WHERE native_identity.identity_authority_id = p_identity_authority_id
               AND native_identity.login_handle = p_login_handle
               AND native_identity.status = 'active'
               AND authority.kind = 'native'
               AND authority.status = 'active'
               AND EXISTS (
                   SELECT 1
                     FROM request_engine.webauthn_credentials AS credential
                    WHERE credential.native_identity_id = native_identity.id
                      AND credential.status = 'active'
               )
        $$;


ALTER FUNCTION request_auth.read_active_webauthn_identity(p_identity_authority_id uuid, p_login_handle text) OWNER TO request_engine_schema_owner;

--
-- Name: read_native_credential_verifier(uuid); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.read_native_credential_verifier(p_credential_id uuid) RETURNS text
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
            SELECT credential.verifier
              FROM request_engine.native_credentials AS credential
              JOIN request_engine.native_identities AS identity
                ON identity.id = credential.native_identity_id
              JOIN request_engine.identity_authorities AS authority
                ON authority.id = identity.identity_authority_id
             WHERE credential.id = p_credential_id
               AND credential.kind = 'password'
               AND credential.status = 'active'
               AND identity.status = 'active'
               AND authority.kind = 'native'
               AND authority.status = 'active'
        $$;


ALTER FUNCTION request_auth.read_native_credential_verifier(p_credential_id uuid) OWNER TO request_engine_schema_owner;

--
-- Name: read_native_password_credential(uuid, text); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.read_native_password_credential(p_identity_authority_id uuid, p_login_handle text) RETURNS TABLE(native_identity_id uuid, credential_id uuid, verifier text, identity_status text, credential_status text, session_epoch bigint, identity_revision bigint, credential_revision bigint)
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
            SELECT i.id,
                   c.id,
                   c.verifier,
                   i.status,
                   c.status,
                   i.session_epoch,
                   i.revision,
                   c.revision
              FROM request_engine.native_identities AS i
              JOIN request_engine.native_credentials AS c
                ON c.native_identity_id = i.id
               AND c.kind = 'password'
               AND c.status = 'active'
              JOIN request_engine.identity_authorities AS authority
                ON authority.id = i.identity_authority_id
               AND authority.kind = 'native' AND authority.status = 'active'
             WHERE i.identity_authority_id = p_identity_authority_id
               AND i.login_handle = p_login_handle
        $$;


ALTER FUNCTION request_auth.read_native_password_credential(p_identity_authority_id uuid, p_login_handle text) OWNER TO request_engine_schema_owner;

--
-- Name: read_native_recovery_addresses(uuid); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.read_native_recovery_addresses(p_native_identity_id uuid) RETURNS TABLE(recovery_address_id uuid, kind text, normalized_address text, status text, revision bigint, verified_at timestamp with time zone, created_at timestamp with time zone)
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
            SELECT address.id,
                   address.kind,
                   address.normalized_address,
                   address.status,
                   address.revision,
                   address.verified_at,
                   address.created_at
              FROM request_engine.native_recovery_addresses AS address
             WHERE address.native_identity_id = p_native_identity_id
               AND address.status <> 'revoked'
             ORDER BY address.created_at, address.id
        $$;


ALTER FUNCTION request_auth.read_native_recovery_addresses(p_native_identity_id uuid) OWNER TO request_engine_schema_owner;

--
-- Name: read_native_recovery_readiness(uuid); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.read_native_recovery_readiness(p_native_identity_id uuid) RETURNS TABLE(recovery_state text, recovery_epoch bigint, last_recovered_at timestamp with time zone, last_recovery_method text, completed_at timestamp with time zone, active_code_set boolean, remaining_codes bigint, active_webauthn_credentials bigint)
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
            SELECT coalesce(rs.state, 'normal'),
                   coalesce(rs.recovery_epoch, 0),
                   rs.last_recovered_at,
                   rs.last_recovery_method,
                   rs.completed_at,
                   EXISTS (
                       SELECT 1
                         FROM request_engine.recovery_code_sets AS code_set
                        WHERE code_set.native_identity_id = p_native_identity_id
                          AND code_set.status = 'active'
                   ),
                   (
                       SELECT count(*)
                         FROM request_engine.recovery_codes AS code
                         JOIN request_engine.recovery_code_sets AS code_set
                           ON code_set.id = code.set_id
                        WHERE code_set.native_identity_id = p_native_identity_id
                          AND code_set.status = 'active'
                          AND code.used_at IS NULL
                   ),
                   (
                       SELECT count(*)
                         FROM request_engine.webauthn_credentials AS credential
                        WHERE credential.native_identity_id = p_native_identity_id
                          AND credential.status = 'active'
                   )
              FROM request_engine.native_identities AS identity
              LEFT JOIN request_engine.native_identity_recovery_state AS rs
                ON rs.native_identity_id = identity.id
             WHERE identity.id = p_native_identity_id
               AND identity.status = 'active'
        $$;


ALTER FUNCTION request_auth.read_native_recovery_readiness(p_native_identity_id uuid) OWNER TO request_engine_schema_owner;

--
-- Name: read_native_recovery_session_password_credential(uuid); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.read_native_recovery_session_password_credential(p_session_id uuid) RETURNS TABLE(credential_id uuid, native_identity_id uuid, verifier text, recovery_epoch bigint)
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
    SELECT credential.id,identity.id,credential.verifier,recovery.recovery_epoch
    FROM request_engine.native_sessions session
    JOIN request_engine.native_identities identity ON identity.id=session.native_identity_id
    JOIN request_engine.identity_authorities authority
      ON authority.id=identity.identity_authority_id
    JOIN request_engine.native_credentials credential ON credential.native_identity_id=identity.id
    JOIN request_engine.native_identity_recovery_state recovery
      ON recovery.native_identity_id=identity.id
    WHERE session.id=p_session_id AND session.status='active'
      AND session.expires_at>statement_timestamp()
      AND identity.status='active' AND identity.session_epoch=session.session_epoch
      AND authority.kind='native' AND authority.status='active'
      AND credential.kind='password' AND credential.status='active'
      AND recovery.state='recovery_restricted'
      AND (EXISTS(SELECT 1 FROM request_engine.native_credentials initial
           WHERE initial.id=session.password_credential_id
             AND initial.native_identity_id=identity.id AND initial.status='active')
        OR EXISTS(SELECT 1 FROM request_engine.webauthn_credentials initial
           WHERE initial.id=session.webauthn_credential_id
             AND initial.native_identity_id=identity.id AND initial.status='active'))
$$;


ALTER FUNCTION request_auth.read_native_recovery_session_password_credential(p_session_id uuid) OWNER TO request_engine_schema_owner;

--
-- Name: read_native_session(uuid); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.read_native_session(p_session_id uuid) RETURNS TABLE(session_id uuid, native_identity_id uuid, identity_authority_id uuid, password_credential_id uuid, password_credential_status text, webauthn_credential_id uuid, webauthn_credential_status text, token_digest bytea, session_epoch bigint, current_session_epoch bigint, session_status text, identity_status text, authority_status text, authentication_methods text[], authentication_assurance text, user_verified boolean, recovery_derived boolean, recovery_restricted boolean, expires_at timestamp with time zone, created_at timestamp with time zone, last_seen_at timestamp with time zone, last_authenticated_at timestamp with time zone)
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
-- Name: read_native_session_password_credential(uuid); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.read_native_session_password_credential(p_session_id uuid) RETURNS TABLE(credential_id uuid, native_identity_id uuid, verifier text)
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
    SELECT credential.id,identity.id,credential.verifier
    FROM request_engine.native_sessions session
    JOIN request_engine.native_identities identity ON identity.id=session.native_identity_id
    JOIN request_engine.identity_authorities authority
      ON authority.id=identity.identity_authority_id
    JOIN request_engine.native_credentials credential ON credential.native_identity_id=identity.id
    LEFT JOIN request_engine.native_identity_recovery_state recovery
      ON recovery.native_identity_id=identity.id
    WHERE session.id=p_session_id AND session.status='active'
      AND session.expires_at>statement_timestamp() AND NOT session.recovery_derived
      AND identity.status='active' AND identity.session_epoch=session.session_epoch
      AND authority.kind='native' AND authority.status='active'
      AND credential.kind='password' AND credential.status='active'
      AND coalesce(recovery.state,'normal')='normal'
      AND (EXISTS(SELECT 1 FROM request_engine.native_credentials initial
           WHERE initial.id=session.password_credential_id
             AND initial.native_identity_id=identity.id AND initial.status='active')
        OR EXISTS(SELECT 1 FROM request_engine.webauthn_credentials initial
           WHERE initial.id=session.webauthn_credential_id
             AND initial.native_identity_id=identity.id AND initial.status='active'))
$$;


ALTER FUNCTION request_auth.read_native_session_password_credential(p_session_id uuid) OWNER TO request_engine_schema_owner;

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
-- Name: read_self_organizations(uuid, text, uuid, integer); Type: FUNCTION; Schema: request_auth; Owner: request_platform_definer
--

CREATE FUNCTION request_auth.read_self_organizations(p_identity_authority_id uuid, p_subject_id text, p_after uuid, p_limit integer) RETURNS TABLE(organization_id uuid, display_name text, principal_id uuid, membership_id uuid)
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        BEGIN
            IF p_limit IS NULL OR p_limit < 1 OR p_limit > 101 THEN
                RAISE EXCEPTION 'Discovery page limit must be between 1 and 101'
                    USING ERRCODE = '22023';
            END IF;
            RETURN QUERY
            SELECT organization.id, organization.display_name, principal.id, membership.id
            FROM request_engine.identity_bindings binding
            JOIN request_engine.identity_authorities authority
              ON authority.id = binding.identity_authority_id AND authority.status = 'active'
            JOIN request_engine.principals principal
              ON principal.id = binding.principal_id
             AND principal.organization_id = binding.organization_id
             AND principal.principal_plane = 'tenant'
             AND principal.principal_kind = 'human' AND principal.active
            JOIN request_engine.staff_memberships membership
              ON membership.organization_id = binding.organization_id
             AND membership.principal_id = principal.id
             AND membership.status = 'active'
            JOIN request_engine.organizations organization
              ON organization.id = binding.organization_id
             AND organization.operational_status = 'active'
            WHERE binding.identity_authority_id = p_identity_authority_id
              AND binding.subject_id = p_subject_id
              AND binding.principal_plane = 'tenant' AND binding.status = 'active'
              AND (p_after IS NULL OR organization.id > p_after)
              AND (authority.kind <> 'native' OR EXISTS (
                  SELECT 1 FROM request_engine.native_identities identity
                  WHERE identity.id::text = binding.subject_id
                    AND identity.identity_authority_id = authority.id AND identity.status = 'active'
              ))
            ORDER BY organization.id LIMIT p_limit;
        END
        $$;


ALTER FUNCTION request_auth.read_self_organizations(p_identity_authority_id uuid, p_subject_id text, p_after uuid, p_limit integer) OWNER TO request_platform_definer;

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
-- Name: read_webauthn_credential_for_assertion(bytea); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.read_webauthn_credential_for_assertion(p_credential_id_bytes bytea) RETURNS TABLE(id uuid, native_identity_id uuid, credential_id bytea, public_key bytea, sign_count bigint, aaguid text, backup_eligible boolean, backup_state boolean, user_verified boolean, status text, user_handle bytea)
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
            SELECT c.id,c.native_identity_id,c.credential_id,c.public_key,c.sign_count,
                   c.aaguid,c.backup_eligible,c.backup_state,c.user_verified,c.status,c.user_handle
              FROM request_engine.webauthn_credentials c
             WHERE c.credential_id=p_credential_id_bytes
        $$;


ALTER FUNCTION request_auth.read_webauthn_credential_for_assertion(p_credential_id_bytes bytea) OWNER TO request_engine_schema_owner;

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
-- Name: reauthenticate_native_session(uuid, uuid, text); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.reauthenticate_native_session(p_session_id uuid, p_credential_id uuid, p_expected_verifier text) RETURNS timestamp with time zone
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
DECLARE
    v_identity uuid;
    v_epoch bigint;
    v_session request_engine.native_sessions%ROWTYPE;
    v_recovery text;
    v_authenticated timestamptz;
BEGIN
    SELECT * INTO v_session FROM request_engine.native_sessions WHERE id=p_session_id;
    v_identity := v_session.native_identity_id;
    IF NOT FOUND OR p_credential_id IS NULL OR p_expected_verifier IS NULL
      THEN RETURN NULL; END IF;
    PERFORM 1 FROM request_engine.identity_authorities authority
      JOIN request_engine.native_identities identity ON identity.identity_authority_id=authority.id
      WHERE identity.id=v_identity AND authority.kind='native' AND authority.status='active'
      FOR SHARE OF authority;
    IF NOT FOUND THEN RETURN NULL; END IF;
    SELECT session_epoch INTO v_epoch FROM request_engine.native_identities
      WHERE id=v_identity AND status='active' FOR UPDATE;
    IF NOT FOUND THEN RETURN NULL; END IF;
    PERFORM 1 FROM request_engine.native_credentials
      WHERE id=p_credential_id AND native_identity_id=v_identity
        AND kind='password' AND status='active' AND verifier=p_expected_verifier FOR SHARE;
    IF NOT FOUND THEN RETURN NULL; END IF;
    IF v_session.password_credential_id IS NOT NULL THEN
        PERFORM 1 FROM request_engine.native_credentials
          WHERE id=v_session.password_credential_id AND native_identity_id=v_identity
            AND kind='password' AND status='active' FOR SHARE;
    ELSE
        PERFORM 1 FROM request_engine.webauthn_credentials
          WHERE id=v_session.webauthn_credential_id AND native_identity_id=v_identity
            AND status='active' FOR SHARE;
    END IF;
    IF NOT FOUND THEN RETURN NULL; END IF;
    SELECT state INTO v_recovery FROM request_engine.native_identity_recovery_state
      WHERE native_identity_id=v_identity FOR SHARE;
    IF FOUND AND v_recovery<>'normal' THEN RETURN NULL; END IF;
    SELECT * INTO v_session FROM request_engine.native_sessions
      WHERE id=p_session_id AND native_identity_id=v_identity FOR UPDATE;
    IF NOT FOUND OR v_session.status<>'active' OR v_session.recovery_derived
       OR v_session.session_epoch<>v_epoch OR v_session.expires_at<=clock_timestamp()
    THEN RETURN NULL; END IF;
    UPDATE request_engine.native_sessions
      SET last_authenticated_at=clock_timestamp(),last_seen_at=clock_timestamp(),
          authentication_methods=ARRAY['password']::text[],
          authentication_assurance='single_factor',user_verified=false
      WHERE id=p_session_id RETURNING last_authenticated_at INTO v_authenticated;
    RETURN v_authenticated;
END $$;


ALTER FUNCTION request_auth.reauthenticate_native_session(p_session_id uuid, p_credential_id uuid, p_expected_verifier text) OWNER TO request_engine_schema_owner;

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
-- Name: staff_invitation_target(uuid, text); Type: FUNCTION; Schema: request_auth; Owner: request_platform_definer
--

CREATE FUNCTION request_auth.staff_invitation_target(p_id uuid, p_digest text) RETURNS uuid
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
            SELECT organization_id FROM request_engine.staff_invitations
                WHERE id=p_id AND token_digest=p_digest
        $$;


ALTER FUNCTION request_auth.staff_invitation_target(p_id uuid, p_digest text) OWNER TO request_platform_definer;

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
-- Name: assert_staff_invitation_manager(); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.assert_staff_invitation_manager() RETURNS uuid
    LANGUAGE sql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$ SELECT request_engine.assert_staff_manager('staff.invite') $$;


ALTER FUNCTION request_cmd.assert_staff_invitation_manager() OWNER TO request_engine_schema_owner;

--
-- Name: assert_staff_invitation_proposer(); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.assert_staff_invitation_proposer() RETURNS uuid
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        DECLARE v_actor uuid; v_org uuid;
        BEGIN
            BEGIN
                v_actor := current_setting('request_engine.authenticated_principal_id',
                    true)::uuid;
                v_org := request_engine.current_organization_id();
            EXCEPTION WHEN invalid_text_representation THEN
                RAISE EXCEPTION 'Tenant actor provenance is malformed' USING ERRCODE = '28000';
            END;
            IF v_actor IS NULL OR v_org IS NULL THEN
                RAISE EXCEPTION 'Tenant actor provenance is required' USING ERRCODE = '28000';
            END IF;
            PERFORM 1 FROM request_engine.principals AS p
              JOIN request_engine.principal_authority_grants AS g
                ON g.principal_id = p.id AND g.organization_id = v_org
               AND g.capability_key = 'staff.propose_invitation'
               AND g.authority_plane = 'operational' AND g.status = 'active'
             WHERE p.id = v_actor AND p.organization_id = v_org
               AND p.principal_plane = 'tenant' AND p.active
               AND ((p.principal_kind = 'human' AND EXISTS(
                        SELECT 1 FROM request_engine.staff_memberships AS m
                         WHERE m.principal_id = p.id AND m.organization_id = v_org
                           AND m.status = 'active'))
                    OR (p.principal_kind = 'agent' AND EXISTS(
                        SELECT 1 FROM request_engine.agent_profiles AS a
                         WHERE a.principal_id = p.id AND a.organization_id = v_org
                           AND a.status = 'active')))
             FOR SHARE OF p, g;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Current Principal lacks staff invitation proposal authority'
                    USING ERRCODE = '42501';
            END IF;
            RETURN v_actor;
        END $$;


ALTER FUNCTION request_cmd.assert_staff_invitation_proposer() OWNER TO request_engine_schema_owner;

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
-- Name: claim_temporary_proof_cleanup(uuid, text, integer, integer); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.claim_temporary_proof_cleanup(p_backend uuid, p_mount text, p_grace_seconds integer, p_lease_seconds integer) RETURNS TABLE(work_id uuid, lease_token uuid, lease_until timestamp with time zone, attempt integer, reference text, version bigint, created_at timestamp with time zone, deletion_at timestamp with time zone, expires_at timestamp with time zone, admitted_at timestamp with time zone)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $_$
        DECLARE instant timestamptz:=clock_timestamp(); chosen uuid; BEGIN
            PERFORM request_engine.assert_temporary_proof_worker();
            IF p_backend IS NULL OR p_backend='00000000-0000-0000-0000-000000000000'
                OR p_mount IS NULL OR p_mount !~ '^[A-Za-z0-9_-]{1,64}$'
                OR p_grace_seconds IS NULL OR p_grace_seconds NOT BETWEEN 1 AND 604800
                OR p_lease_seconds IS NULL OR p_lease_seconds NOT BETWEEN 10 AND 3600 THEN
                RAISE EXCEPTION 'invalid cleanup claim input' USING ERRCODE='22023';
            END IF;
            INSERT INTO request_engine.temporary_proof_cleanup_work
                (backend_id,mount,reference,version,created_at,next_attempt_at)
            SELECT r.backend_id,r.mount,r.reference,r.version,r.created_at,instant
            FROM request_engine.temporary_proof_retention_receipts r
            WHERE r.backend_id=p_backend AND r.mount=p_mount
              AND r.expires_at+make_interval(secs=>p_grace_seconds)<=instant
              AND NOT EXISTS(SELECT 1 FROM request_engine.temporary_proof_cleanup_work w
                WHERE (w.backend_id,w.mount,w.reference,w.version,w.created_at)=
                    (r.backend_id,r.mount,r.reference,r.version,r.created_at))
            ORDER BY r.expires_at,r.created_at,r.reference,r.version LIMIT 100
            ON CONFLICT DO NOTHING;
            SELECT w.id INTO chosen FROM request_engine.temporary_proof_cleanup_work w
            JOIN request_engine.temporary_proof_retention_receipts r
              USING(backend_id,mount,reference,version,created_at)
            WHERE w.backend_id=p_backend AND w.mount=p_mount AND NOT w.terminal
              AND w.next_attempt_at<=instant AND (w.lease_until IS NULL OR w.lease_until<=instant)
              AND r.expires_at+make_interval(secs=>p_grace_seconds)<=instant
            ORDER BY w.next_attempt_at,w.id FOR UPDATE OF w SKIP LOCKED LIMIT 1;
            IF chosen IS NULL THEN RETURN; END IF;
            UPDATE request_engine.temporary_proof_cleanup_work w
            SET lease_token=gen_random_uuid(),
                lease_until=instant+make_interval(secs=>p_lease_seconds),
                attempts=w.attempts+1 WHERE w.id=chosen;
            RETURN QUERY SELECT w.id,w.lease_token,w.lease_until,w.attempts,
                r.reference,r.version,r.created_at,r.deletion_at,r.expires_at,instant
            FROM request_engine.temporary_proof_cleanup_work w
            JOIN request_engine.temporary_proof_retention_receipts r
              USING(backend_id,mount,reference,version,created_at) WHERE w.id=chosen;
        END $_$;


ALTER FUNCTION request_cmd.claim_temporary_proof_cleanup(p_backend uuid, p_mount text, p_grace_seconds integer, p_lease_seconds integer) OWNER TO request_engine_schema_owner;

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
-- Name: finish_temporary_proof_cleanup(uuid, uuid, text, uuid, text, integer); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.finish_temporary_proof_cleanup(p_work uuid, p_lease uuid, p_outcome text, p_admission uuid, p_digest text, p_retry_seconds integer) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $_$
        DECLARE work request_engine.temporary_proof_cleanup_work; BEGIN
            PERFORM request_engine.assert_temporary_proof_worker();
            IF p_work IS NULL OR p_lease IS NULL OR p_outcome IS NULL OR p_outcome NOT IN
                ('destroyed','absent','unverified','denied','unresolved','retained')
                OR p_admission IS NULL OR p_admission='00000000-0000-0000-0000-000000000000'
                OR p_digest IS NULL OR p_digest !~ '^[0-9a-f]{64}$'
                OR p_retry_seconds IS NULL OR p_retry_seconds NOT BETWEEN 1 AND 86400 THEN
                RAISE EXCEPTION 'invalid cleanup result input' USING ERRCODE='22023';
            END IF;
            SELECT * INTO work FROM request_engine.temporary_proof_cleanup_work
                WHERE id=p_work FOR UPDATE;
            IF work.id IS NULL OR work.terminal OR work.lease_token IS DISTINCT FROM p_lease
                OR work.lease_until<=clock_timestamp() THEN RETURN false; END IF;
            INSERT INTO request_engine.temporary_proof_cleanup_results
                (work_id,lease_token,attempt,outcome,admission_id,admission_digest)
            VALUES(work.id,p_lease,work.attempts,p_outcome,p_admission,p_digest);
            UPDATE request_engine.temporary_proof_cleanup_work SET
                terminal=p_outcome IN('destroyed','absent','unverified','denied'),
                lease_token=NULL,lease_until=NULL,
                next_attempt_at=clock_timestamp()+make_interval(secs=>p_retry_seconds)
            WHERE id=p_work;
            RETURN true;
        END $_$;


ALTER FUNCTION request_cmd.finish_temporary_proof_cleanup(p_work uuid, p_lease uuid, p_outcome text, p_admission uuid, p_digest text, p_retry_seconds integer) OWNER TO request_engine_schema_owner;

--
-- Name: lock_agent_credential_manager(uuid); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.lock_agent_credential_manager(p_target uuid) RETURNS uuid
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        DECLARE
            v_org uuid := request_engine.current_organization_id();
            v_actor uuid := NULLIF(current_setting(
                'request_engine.authenticated_principal_id', true), '')::uuid;
            v_identity uuid;
            v_status text;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
            PERFORM 1 FROM request_engine.principals
             WHERE organization_id=v_org AND id=v_actor AND principal_plane='tenant'
               AND principal_kind='human' AND active FOR SHARE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Current HUMAN manager required' USING ERRCODE='42501';
            END IF;
            -- Membership/grant writers serialize on this Principal. Do not acquire
            -- their row locks after it: a trigger may already wait for this root.
            IF NOT EXISTS(SELECT 1 FROM request_engine.staff_memberships
                WHERE organization_id=v_org AND principal_id=v_actor AND status='active')
               OR NOT EXISTS(SELECT 1 FROM request_engine.principal_authority_grants
                WHERE organization_id=v_org AND principal_id=v_actor AND status='active'
                  AND authority_plane='tenant_control' AND capability_key='agent.manage_authority')
            THEN
                RAISE EXCEPTION 'Current agent manager authority required' USING ERRCODE='42501';
            END IF;
            SELECT workload_identity_id, status INTO v_identity,v_status
              FROM request_engine.agent_profiles
             WHERE organization_id=v_org AND principal_id=p_target FOR SHARE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Agent not found' USING ERRCODE='P0002';
            END IF;
            IF v_status NOT IN ('pending','active','suspended') THEN
                RAISE EXCEPTION 'Revoked agent cannot rotate' USING ERRCODE='55000';
            END IF;
            PERFORM 1 FROM request_engine.principals
             WHERE organization_id=v_org AND id=p_target AND principal_kind='agent'
               AND principal_plane='tenant' FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Agent not found' USING ERRCODE='P0002';
            END IF;
            IF EXISTS(SELECT 1 FROM request_engine.principal_authority_grants target
                WHERE target.organization_id=v_org AND target.principal_id=p_target
                  AND target.status='active' AND (target.authority_plane<>'operational'
                  OR target.delegable OR NOT EXISTS(
                    SELECT 1 FROM request_engine.principal_authority_grants manager
                     WHERE manager.organization_id=v_org AND manager.principal_id=v_actor
                       AND manager.capability_key=target.capability_key
                       AND manager.authority_plane='operational' AND manager.status='active'
                       AND manager.delegable))) THEN
                RAISE EXCEPTION 'Agent exceeds current manager ceiling' USING ERRCODE='42501';
            END IF;
            PERFORM 1 FROM request_engine.workload_identities wi
              JOIN request_engine.identity_bindings b
                ON b.identity_authority_id=wi.identity_authority_id AND b.subject_id=wi.id::text
              JOIN request_engine.identity_authorities authority
                ON authority.id=wi.identity_authority_id
             WHERE wi.id=v_identity AND wi.workload_kind='agent' AND wi.status='active'
               AND b.organization_id=v_org AND b.principal_id=p_target
               AND b.status IN ('pending','active','suspended')
               AND authority.kind='workload' AND authority.status='active'
             FOR UPDATE OF wi FOR SHARE OF b,authority;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Agent identity is not usable' USING ERRCODE='55000';
            END IF;
            RETURN v_identity;
        END $$;


ALTER FUNCTION request_cmd.lock_agent_credential_manager(p_target uuid) OWNER TO request_engine_schema_owner;

--
-- Name: lock_controller_policy_upgrade_authority(); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.lock_controller_policy_upgrade_authority() RETURNS uuid
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
            PERFORM request_engine.lock_tenant_staff_root();
            RETURN request_engine.assert_staff_manager('controller_policy_upgrade');
        END;
        $$;


ALTER FUNCTION request_cmd.lock_controller_policy_upgrade_authority() OWNER TO request_engine_schema_owner;

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
