"""WebAuthn P2 trust-boundary hardening after adversarial review.

Revision ID: 0061_webauthn_trust_fixes
Revises: 0060_webauthn_sessions

Closes findings from the P2 security/concurrency review without rewriting 0059/0060:

- ``finalize_webauthn_step_up`` uses the canonical authority -> identity ->
  credential -> session lock order, removing a session/credential deadlock with
  credential revocation and identity disable, and validates the identity's current
  session epoch under lock;
- ``finalize_webauthn_registration`` gates on the native authority status like
  authentication does, so a suspended authority cannot register new credentials;
- ``revoke_webauthn_credential`` also invalidates active sessions of the identity
  whose proven methods include WebAuthn, so a stepped-up password session cannot
  retain phishing-resistant assurance after the proving credential is revoked;
- ``create_webauthn_challenge`` serializes challenge creation per scope so the
  expire-then-insert cannot race; concurrent ceremonies for one scope remain
  possible (single-use, scope-bound challenges are the replay defense);
- ``native_sessions`` enforces stored assurance equal to the value derived from
  its proven methods, user verification and recovery state;
- ``reauthenticate_native_session`` also compares the identity's current session
  epoch.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0061_webauthn_trust_fixes"
down_revision: str | Sequence[str] | None = "0060_webauthn_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RUNTIME = "request_engine_app"
_OWNER = "request_engine_schema_owner"

_REPLACED_FUNCTIONS = (
    (
        "finalize_webauthn_registration(bytea, uuid, bytea, bytea, bigint, text, "
        "boolean, boolean, boolean)"
    ),
    "finalize_webauthn_step_up(bytea, uuid, uuid, uuid, bigint, boolean, boolean)",
    "revoke_webauthn_credential(uuid, uuid, text)",
    "reauthenticate_native_session(uuid, uuid)",
    "create_webauthn_challenge(uuid, text, uuid, uuid, uuid, bytea, timestamptz)",
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")

    # Stored assurance must equal the value derived from the proven ceremony.
    op.execute(
        """
        ALTER TABLE request_engine.native_sessions
            ADD CONSTRAINT native_sessions_assurance_derivation_check CHECK (
                authentication_assurance = request_engine.derive_authentication_assurance(
                    authentication_methods, user_verified, recovery_derived
                )
            );
        """
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

            -- Serialize challenge creation per scope so two concurrent begins
            -- cannot both leave a live challenge.
            PERFORM pg_advisory_xact_lock(
                hashtextextended(
                    coalesce(p_purpose, '') || '|'
                    || coalesce(p_native_identity_id::text, '') || '|'
                    || coalesce(p_session_id::text, '') || '|'
                    || coalesce(p_setup_session_id::text, ''),
                    0
                )
            );

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

        CREATE OR REPLACE FUNCTION request_auth.finalize_webauthn_registration(
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

        CREATE OR REPLACE FUNCTION request_auth.finalize_webauthn_step_up(
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
        """
    )

    for signature in _REPLACED_FUNCTIONS:
        op.execute(f"ALTER FUNCTION request_auth.{signature} OWNER TO {_OWNER}")
        op.execute(f"REVOKE ALL ON FUNCTION request_auth.{signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION request_auth.{signature} TO {_RUNTIME}")


def downgrade() -> None:
    raise RuntimeError("WebAuthn trust-boundary hardening is append-preserving; roll forward")
