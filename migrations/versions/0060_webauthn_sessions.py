"""Method-neutral native sessions and race-safe WebAuthn finalization.

Revision ID: 0060_webauthn_sessions
Revises: 0059_webauthn_credentials

Implements the remaining P2 trust-boundary work of ADR 0014 §5.5/§5.5.1 and §11:

- ``native_sessions`` becomes method-neutral. A session records exactly one
  initial authenticator (password *or* WebAuthn), the authentication methods
  actually proven, the derived assurance, whether user verification was accepted
  and whether it is recovery-derived. Existing password sessions are backfilled.
- challenge consumption is coupled to the authoritative consequence in a single
  transaction (registration, authentication session issuance, step-up), so a
  failed verification can never leave a consumed challenge with no effect and a
  concurrent replay yields exactly one winner;
- the ``step_up`` challenge purpose exists;
- sign counters are persisted as a race-safe high-water mark with regression
  telemetry, never a blind caller-supplied write.

Challenge verification itself stays in Python outside these transactions; only
the trusted finalization touches authoritative locks. Raw challenges never reach
durable storage.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0060_webauthn_sessions"
down_revision: str | Sequence[str] | None = "0059_webauthn_credentials"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RUNTIME = "request_engine_app"
_OWNER = "request_engine_schema_owner"

_NEW_FUNCTIONS = (
    "read_webauthn_challenge(bytea, text)",
    "read_webauthn_credential(bytea)",
    (
        "finalize_webauthn_registration(bytea, uuid, bytea, bytea, bigint, text, "
        "boolean, boolean, boolean)"
    ),
    (
        "finalize_webauthn_authentication(bytea, uuid, uuid, bigint, boolean, boolean, "
        "boolean, uuid, bytea, text, timestamptz)"
    ),
    "finalize_webauthn_step_up(bytea, uuid, uuid, uuid, bigint, boolean, boolean)",
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")

    # --- Method-neutral session model -------------------------------------
    op.execute(
        """
        ALTER TABLE request_engine.native_sessions
            RENAME COLUMN credential_id TO password_credential_id;
        ALTER TABLE request_engine.native_sessions
            ALTER COLUMN password_credential_id DROP NOT NULL;
        ALTER TABLE request_engine.native_sessions
            ADD COLUMN webauthn_credential_id uuid
                REFERENCES request_engine.webauthn_credentials(id);
        ALTER TABLE request_engine.native_sessions
            ADD COLUMN authentication_methods text[] NOT NULL
                DEFAULT ARRAY['password']::text[];
        ALTER TABLE request_engine.native_sessions
            ADD COLUMN authentication_assurance text NOT NULL DEFAULT 'single_factor';
        ALTER TABLE request_engine.native_sessions
            ADD COLUMN user_verified boolean NOT NULL DEFAULT false;
        ALTER TABLE request_engine.native_sessions
            ADD COLUMN recovery_derived boolean NOT NULL DEFAULT false;
        ALTER TABLE request_engine.native_sessions
            ADD CONSTRAINT native_sessions_initial_authenticator_check CHECK (
                (password_credential_id IS NOT NULL)
                <> (webauthn_credential_id IS NOT NULL)
            );
        ALTER TABLE request_engine.native_sessions
            ADD CONSTRAINT native_sessions_methods_check CHECK (
                cardinality(authentication_methods) >= 1
                AND authentication_methods <@ ARRAY[
                    'password', 'webauthn', 'totp', 'recovery_code'
                ]::text[]
            );
        ALTER TABLE request_engine.native_sessions
            ADD CONSTRAINT native_sessions_assurance_check CHECK (
                authentication_assurance IN (
                    'single_factor', 'mfa', 'phishing_resistant', 'recovery'
                )
            );
        ALTER TABLE request_engine.native_sessions
            ADD CONSTRAINT native_sessions_user_verified_check CHECK (
                NOT user_verified OR 'webauthn' = ANY(authentication_methods)
            );
        ALTER TABLE request_engine.native_sessions
            ADD CONSTRAINT native_sessions_recovery_check CHECK (
                recovery_derived = ('recovery_code' = ANY(authentication_methods))
            );
        ALTER TABLE request_engine.native_sessions
            ADD CONSTRAINT native_sessions_recovery_assurance_check CHECK (
                (authentication_assurance = 'recovery') = recovery_derived
            );
        ALTER TABLE request_engine.native_sessions
            ADD CONSTRAINT native_sessions_phishing_check CHECK (
                authentication_assurance <> 'phishing_resistant'
                OR (user_verified AND 'webauthn' = ANY(authentication_methods))
            );
        CREATE INDEX native_sessions_webauthn_credential_active_idx
            ON request_engine.native_sessions (webauthn_credential_id)
            WHERE status = 'active';
        """
    )

    # --- Shared assurance derivation (structural consistency backstop) ----
    op.execute(
        """
        CREATE FUNCTION request_engine.derive_authentication_assurance(
            p_methods text[],
            p_user_verified boolean,
            p_recovery_derived boolean
        ) RETURNS text
        LANGUAGE sql IMMUTABLE
        SET search_path TO 'pg_catalog'
        AS $$
            SELECT CASE
                WHEN p_methods IS NULL OR cardinality(p_methods) = 0 THEN NULL
                WHEN p_recovery_derived OR 'recovery_code' = ANY(p_methods)
                    THEN 'recovery'
                WHEN 'webauthn' = ANY(p_methods) AND p_user_verified
                    THEN 'phishing_resistant'
                WHEN cardinality(p_methods)
                     - (CASE WHEN 'recovery_code' = ANY(p_methods) THEN 1 ELSE 0 END) >= 2
                    THEN 'mfa'
                ELSE 'single_factor'
            END
        $$;
        ALTER FUNCTION request_engine.derive_authentication_assurance(
            text[], boolean, boolean
        ) OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_engine.derive_authentication_assurance(
            text[], boolean, boolean
        ) FROM PUBLIC;

        CREATE FUNCTION request_engine.authentication_assurance_rank(
            p_assurance text
        ) RETURNS integer
        LANGUAGE sql IMMUTABLE
        SET search_path TO 'pg_catalog'
        AS $$
            SELECT CASE p_assurance
                WHEN 'single_factor' THEN 0
                WHEN 'mfa' THEN 1
                WHEN 'phishing_resistant' THEN 2
                ELSE 0
            END
        $$;
        ALTER FUNCTION request_engine.authentication_assurance_rank(text)
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_engine.authentication_assurance_rank(text)
            FROM PUBLIC;
        """
    )

    # --- Session guard: frozen initial authenticator, monotonic evidence --
    op.execute(
        r"""
        CREATE OR REPLACE FUNCTION request_engine.guard_native_session()
        RETURNS trigger LANGUAGE plpgsql
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                NEW.last_authenticated_at := NEW.created_at;
                RETURN NEW;
            END IF;
            IF ROW(NEW.id, NEW.native_identity_id, NEW.password_credential_id,
                   NEW.webauthn_credential_id, NEW.token_digest, NEW.token_fingerprint,
                   NEW.session_epoch, NEW.created_at, NEW.expires_at, NEW.recovery_derived)
               IS DISTINCT FROM
               ROW(OLD.id, OLD.native_identity_id, OLD.password_credential_id,
                   OLD.webauthn_credential_id, OLD.token_digest, OLD.token_fingerprint,
                   OLD.session_epoch, OLD.created_at, OLD.expires_at, OLD.recovery_derived)
            THEN
                RAISE EXCEPTION 'Native session credential material is immutable'
                    USING ERRCODE = '55000';
            END IF;
            IF NOT (OLD.authentication_methods <@ NEW.authentication_methods) THEN
                RAISE EXCEPTION 'Native session authentication methods may only grow'
                    USING ERRCODE = '55000';
            END IF;
            IF OLD.user_verified AND NOT NEW.user_verified THEN
                RAISE EXCEPTION 'Native session user verification may not be removed'
                    USING ERRCODE = '55000';
            END IF;
            IF OLD.authentication_assurance <> 'recovery'
               AND NEW.authentication_assurance <> 'recovery'
               AND request_engine.authentication_assurance_rank(NEW.authentication_assurance)
                   < request_engine.authentication_assurance_rank(OLD.authentication_assurance)
            THEN
                RAISE EXCEPTION 'Native session assurance may not be downgraded'
                    USING ERRCODE = '55000';
            END IF;
            IF NEW.status = OLD.status
               AND NEW.revoked_at IS NOT DISTINCT FROM OLD.revoked_at
               AND NEW.revocation_reason IS NOT DISTINCT FROM OLD.revocation_reason
               AND (OLD.last_seen_at IS NULL OR NEW.last_seen_at >= OLD.last_seen_at)
               AND (
                   OLD.last_authenticated_at IS NULL
                   OR NEW.last_authenticated_at >= OLD.last_authenticated_at
               )
            THEN
                RETURN NEW;
            END IF;
            IF OLD.status = 'active'
               AND NEW.status = 'revoked'
               AND NEW.revoked_at IS NOT NULL
               AND length(btrim(NEW.revocation_reason)) BETWEEN 1 AND 200
            THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'Invalid Native session mutation' USING ERRCODE = '55000';
        END
        $$;
        ALTER FUNCTION request_engine.guard_native_session()
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_engine.guard_native_session() FROM PUBLIC;
        """
    )

    # --- Replace password session creation for the renamed column ---------
    op.execute(
        r"""
        CREATE OR REPLACE FUNCTION request_auth.create_native_session(
            p_native_identity_id uuid,
            p_credential_id uuid,
            p_session_id uuid,
            p_token_digest bytea,
            p_token_fingerprint text,
            p_expires_at timestamptz
        ) RETURNS boolean
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
        DECLARE
            v_epoch bigint;
            v_identity_status text;
            v_credential_status text;
        BEGIN
            PERFORM 1
              FROM request_engine.identity_authorities AS authority
              JOIN request_engine.native_identities AS native_identity
                ON native_identity.identity_authority_id = authority.id
             WHERE native_identity.id = p_native_identity_id
               AND authority.kind = 'native' AND authority.status = 'active'
             FOR SHARE OF authority;
            IF NOT FOUND THEN RETURN false; END IF;

            SELECT session_epoch, status
              INTO v_epoch, v_identity_status
              FROM request_engine.native_identities
             WHERE id = p_native_identity_id
             FOR UPDATE;
            IF NOT FOUND OR v_identity_status <> 'active' THEN
                RETURN false;
            END IF;

            SELECT status
              INTO v_credential_status
              FROM request_engine.native_credentials
             WHERE id = p_credential_id
               AND native_identity_id = p_native_identity_id
               AND kind = 'password'
             FOR UPDATE;
            IF NOT FOUND OR v_credential_status <> 'active' THEN
                RETURN false;
            END IF;
            IF p_expires_at <= clock_timestamp() THEN
                RETURN false;
            END IF;

            INSERT INTO request_engine.native_sessions (
                id, native_identity_id, password_credential_id, token_digest,
                token_fingerprint, session_epoch, expires_at
            ) VALUES (
                p_session_id, p_native_identity_id, p_credential_id, p_token_digest,
                p_token_fingerprint, v_epoch, p_expires_at
            );
            UPDATE request_engine.native_credentials
               SET last_used_at = clock_timestamp()
             WHERE id = p_credential_id;
            RETURN true;
        END
        $$;
        """
    )

    # --- Read boundary exposes method-neutral evidence --------------------
    op.execute("DROP FUNCTION request_auth.read_native_session(uuid)")
    op.execute(
        """
        CREATE FUNCTION request_auth.read_native_session(p_session_id uuid)
        RETURNS TABLE (
            session_id uuid,
            native_identity_id uuid,
            identity_authority_id uuid,
            password_credential_id uuid,
            password_credential_status text,
            webauthn_credential_id uuid,
            webauthn_credential_status text,
            token_digest bytea,
            session_epoch bigint,
            current_session_epoch bigint,
            session_status text,
            identity_status text,
            authority_status text,
            authentication_methods text[],
            authentication_assurance text,
            user_verified boolean,
            recovery_derived boolean,
            expires_at timestamptz,
            created_at timestamptz,
            last_seen_at timestamptz,
            last_authenticated_at timestamptz
        )
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
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
              JOIN request_engine.identity_authorities AS a
                ON a.id = i.identity_authority_id
               AND a.kind = 'native'
             WHERE s.id = p_session_id
        $$;
        ALTER FUNCTION request_auth.read_native_session(uuid)
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_auth.read_native_session(uuid) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_auth.read_native_session(uuid) TO request_engine_app;
        """
    )
    op.execute(
        r"""
        CREATE OR REPLACE FUNCTION request_auth.reauthenticate_native_session(
            p_session_id uuid,
            p_credential_id uuid
        ) RETURNS timestamptz
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
        DECLARE
            v_native_identity_id uuid;
            v_status text;
            v_expires_at timestamptz;
            v_authenticated_at timestamptz;
        BEGIN
            IF p_session_id IS NULL OR p_credential_id IS NULL THEN
                RETURN NULL;
            END IF;

            SELECT session.native_identity_id, session.status, session.expires_at
              INTO v_native_identity_id, v_status, v_expires_at
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
        """
    )

    # --- Challenge lifecycle: step_up purpose, non-consuming read ---------
    op.execute(
        """
        ALTER TABLE request_engine.webauthn_challenges
            DROP CONSTRAINT webauthn_challenges_purpose_check;
        ALTER TABLE request_engine.webauthn_challenges
            ADD CONSTRAINT webauthn_challenges_purpose_check CHECK (
                purpose IN ('registration', 'authentication', 'step_up')
            );
        """
    )
    op.execute("DROP FUNCTION request_auth.consume_webauthn_challenge(bytea, text)")
    op.execute(
        "DROP FUNCTION request_auth.update_webauthn_credential_sign_count(uuid, uuid, bigint)"
    )
    # Registration must be coupled to challenge consumption; the standalone
    # credential insert (which bypassed challenge binding) is removed.
    op.execute(
        "DROP FUNCTION request_auth.register_webauthn_credential("
        "uuid, uuid, bytea, bytea, bigint, text, boolean, boolean, boolean)"
    )
    op.execute(
        r"""
        CREATE OR REPLACE FUNCTION request_auth.create_webauthn_challenge(
            p_challenge_id uuid,
            p_purpose text,
            p_native_identity_id uuid,
            p_session_id uuid,
            p_setup_session_id uuid,
            p_challenge_digest bytea,
            p_expires_at timestamptz
        ) RETURNS boolean
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
        DECLARE
            v_scope_count integer;
        BEGIN
            v_scope_count := (p_native_identity_id IS NOT NULL)::int
                + (p_session_id IS NOT NULL)::int
                + (p_setup_session_id IS NOT NULL)::int;
            IF p_challenge_id IS NULL
               OR p_challenge_digest IS NULL
               OR octet_length(p_challenge_digest) <> 32
               OR p_purpose NOT IN ('registration', 'authentication', 'step_up')
               OR v_scope_count <> 1
               OR p_expires_at <= clock_timestamp()
            THEN
                RETURN false;
            END IF;

            UPDATE request_engine.webauthn_challenges
               SET status = 'expired'
             WHERE status = 'pending'
               AND purpose = p_purpose
               AND native_identity_id IS NOT DISTINCT FROM p_native_identity_id
               AND session_id IS NOT DISTINCT FROM p_session_id
               AND setup_session_id IS NOT DISTINCT FROM p_setup_session_id;

            INSERT INTO request_engine.webauthn_challenges (
                id, purpose, native_identity_id, session_id, setup_session_id,
                challenge_digest, expires_at
            ) VALUES (
                p_challenge_id, p_purpose, p_native_identity_id, p_session_id,
                p_setup_session_id, p_challenge_digest, p_expires_at
            );
            RETURN true;
        END
        $$;
        """
    )
    op.execute(
        """
        ALTER TABLE request_engine.webauthn_credentials
            ADD COLUMN last_regression_at timestamptz;
        """
    )
    op.execute(
        r"""
        CREATE FUNCTION request_auth.read_webauthn_challenge(
            p_challenge_digest bytea,
            p_purpose text
        )
        RETURNS TABLE (
            challenge_id uuid,
            native_identity_id uuid,
            session_id uuid,
            setup_session_id uuid,
            expires_at timestamptz
        )
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
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

        CREATE FUNCTION request_auth.read_webauthn_credential(
            p_credential_id_bytes bytea
        )
        RETURNS TABLE (
            id uuid,
            native_identity_id uuid,
            credential_id bytea,
            public_key bytea,
            sign_count bigint,
            aaguid text,
            backup_eligible boolean,
            backup_state boolean,
            user_verified boolean,
            status text
        )
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
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

        CREATE FUNCTION request_auth.finalize_webauthn_registration(
            p_challenge_digest bytea,
            p_credential_row_id uuid,
            p_credential_id_bytes bytea,
            p_public_key bytea,
            p_sign_count bigint,
            p_aaguid text,
            p_backup_eligible boolean,
            p_backup_state boolean,
            p_user_verified boolean
        ) RETURNS boolean
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
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
            IF NOT FOUND OR v_challenge.native_identity_id IS NULL THEN
                RETURN false;
            END IF;

            SELECT identity.status INTO v_identity_status
              FROM request_engine.native_identities AS identity
             WHERE identity.id = v_challenge.native_identity_id
             FOR UPDATE;
            IF NOT FOUND OR v_identity_status <> 'active' THEN
                RETURN false;
            END IF;

            INSERT INTO request_engine.webauthn_credentials (
                id, native_identity_id, credential_id, public_key, sign_count,
                aaguid, backup_eligible, backup_state, user_verified
            ) VALUES (
                p_credential_row_id, v_challenge.native_identity_id,
                p_credential_id_bytes, p_public_key, p_sign_count, p_aaguid,
                p_backup_eligible, p_backup_state, p_user_verified
            )
            ON CONFLICT (credential_id) DO NOTHING;
            IF NOT FOUND THEN
                RETURN false;
            END IF;

            UPDATE request_engine.webauthn_challenges
               SET status = 'consumed', consumed_at = clock_timestamp()
             WHERE id = v_challenge.id;
            RETURN true;
        END
        $$;

        CREATE FUNCTION request_auth.finalize_webauthn_authentication(
            p_challenge_digest bytea,
            p_credential_row_id uuid,
            p_native_identity_id uuid,
            p_sign_count bigint,
            p_backup_eligible boolean,
            p_backup_state boolean,
            p_user_verified boolean,
            p_session_id uuid,
            p_token_digest bytea,
            p_token_fingerprint text,
            p_expires_at timestamptz
        ) RETURNS boolean
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
        DECLARE
            v_challenge request_engine.webauthn_challenges%ROWTYPE;
            v_epoch bigint;
            v_identity_status text;
            v_credential_status text;
        BEGIN
            IF p_challenge_digest IS NULL
               OR octet_length(p_challenge_digest) <> 32
               OR p_credential_row_id IS NULL
               OR p_native_identity_id IS NULL
               OR p_sign_count < 0
               OR p_session_id IS NULL
               OR p_token_digest IS NULL
               OR octet_length(p_token_digest) <> 32
               OR p_token_fingerprint IS NULL
               OR p_token_fingerprint !~ '^[0-9a-f]{16}$'
               OR p_expires_at IS NULL
            THEN
                RETURN false;
            END IF;

            SELECT challenge.* INTO v_challenge
              FROM request_engine.webauthn_challenges AS challenge
             WHERE challenge.challenge_digest = p_challenge_digest
               AND challenge.purpose = 'authentication'
               AND challenge.status = 'pending'
               AND challenge.expires_at > clock_timestamp()
             FOR UPDATE;
            IF NOT FOUND
               OR v_challenge.native_identity_id IS DISTINCT FROM p_native_identity_id
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

            SELECT session_epoch, status
              INTO v_epoch, v_identity_status
              FROM request_engine.native_identities
             WHERE id = p_native_identity_id
             FOR UPDATE;
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
            IF p_expires_at <= clock_timestamp() THEN
                RETURN false;
            END IF;

            UPDATE request_engine.webauthn_credentials
               SET sign_count = GREATEST(sign_count, p_sign_count),
                   last_used_at = clock_timestamp(),
                   backup_state = p_backup_state,
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

            INSERT INTO request_engine.native_sessions (
                id, native_identity_id, password_credential_id,
                webauthn_credential_id, token_digest, token_fingerprint,
                session_epoch, expires_at, authentication_methods,
                authentication_assurance, user_verified, recovery_derived
            ) VALUES (
                p_session_id, p_native_identity_id, NULL, p_credential_row_id,
                p_token_digest, p_token_fingerprint, v_epoch, p_expires_at,
                ARRAY['webauthn']::text[],
                request_engine.derive_authentication_assurance(
                    ARRAY['webauthn']::text[], p_user_verified, false
                ),
                p_user_verified, false
            );

            UPDATE request_engine.webauthn_challenges
               SET status = 'consumed', consumed_at = clock_timestamp()
             WHERE id = v_challenge.id;
            RETURN true;
        END
        $$;

        CREATE FUNCTION request_auth.finalize_webauthn_step_up(
            p_challenge_digest bytea,
            p_credential_row_id uuid,
            p_session_id uuid,
            p_native_identity_id uuid,
            p_sign_count bigint,
            p_backup_eligible boolean,
            p_user_verified boolean
        ) RETURNS boolean
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
        DECLARE
            v_challenge request_engine.webauthn_challenges%ROWTYPE;
            v_session request_engine.native_sessions%ROWTYPE;
            v_credential_status text;
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
            IF NOT FOUND
               OR v_challenge.session_id IS DISTINCT FROM p_session_id
            THEN
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
            THEN
                RETURN false;
            END IF;

            PERFORM 1
              FROM request_engine.native_identities AS identity
              JOIN request_engine.identity_authorities AS authority
                ON authority.id = identity.identity_authority_id
             WHERE identity.id = p_native_identity_id
               AND identity.status = 'active'
               AND identity.session_epoch = v_session.session_epoch
               AND authority.kind = 'native'
               AND authority.status = 'active';
            IF NOT FOUND THEN
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

            UPDATE request_engine.webauthn_challenges
               SET status = 'consumed', consumed_at = clock_timestamp()
             WHERE id = v_challenge.id;
            RETURN true;
        END
        $$;
        """
    )

    # --- Credential revocation also invalidates its sessions --------------
    op.execute(
        r"""
        CREATE OR REPLACE FUNCTION request_auth.revoke_webauthn_credential(
            p_credential_id uuid,
            p_native_identity_id uuid,
            p_reason text
        ) RETURNS boolean
        LANGUAGE plpgsql
        SECURITY DEFINER
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
            UPDATE request_engine.native_sessions
               SET status = 'revoked',
                   revoked_at = clock_timestamp(),
                   revocation_reason = 'webauthn_credential_revoked'
             WHERE webauthn_credential_id = p_credential_id
               AND status = 'active';
            RETURN true;
        END
        $$;
        """
    )

    for signature in _NEW_FUNCTIONS:
        op.execute(f"ALTER FUNCTION request_auth.{signature} OWNER TO {_OWNER}")
        op.execute(f"REVOKE ALL ON FUNCTION request_auth.{signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION request_auth.{signature} TO {_RUNTIME}")
    # Re-created functions keep their prior grants, but re-assert ownership.
    for signature in (
        "create_native_session(uuid, uuid, uuid, bytea, text, timestamptz)",
        "reauthenticate_native_session(uuid, uuid)",
        "revoke_webauthn_credential(uuid, uuid, text)",
    ):
        op.execute(f"ALTER FUNCTION request_auth.{signature} OWNER TO {_OWNER}")


def downgrade() -> None:
    raise RuntimeError("Method-neutral sessions are append-preserving; roll forward")
