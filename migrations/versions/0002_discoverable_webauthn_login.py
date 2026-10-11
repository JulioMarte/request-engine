"""Discoverable (usernameless) WebAuthn authentication.

Adds a challenge purpose for an unbound authentication ceremony and a finalizer
that resolves the owning native identity from the presented credential, without
accepting a caller-supplied identity. All other guarantees are unchanged: the
challenge is still single-purpose, single-use, TTL-bounded and consumed in the
same transaction that writes the session, and assurance is still derived from the
verified ceremony.

Revision ID: 0002_discoverable_webauthn_login
Revises: 0001_initial
Create Date: 2026-09-28
"""

from alembic import op

revision: str = "0002_discoverable_webauthn_login"
down_revision: str | None = "0001_initial"
branch_labels: str | None = None
depends_on: str | None = None

_DISCOVERABLE_FINALIZE_SIGNATURE = (
    "bytea, uuid, bigint, boolean, boolean, boolean, uuid, bytea, text, timestamp with time zone"
)

_ORIGINAL_PURPOSE_CHECK = """
ALTER TABLE request_engine.webauthn_challenges
    DROP CONSTRAINT webauthn_challenges_purpose_check;
ALTER TABLE request_engine.webauthn_challenges
    ADD CONSTRAINT webauthn_challenges_purpose_check
    CHECK ((purpose = ANY (ARRAY['registration'::text, 'authentication'::text, 'step_up'::text])));
"""

_ORIGINAL_SCOPE_CHECK = """
ALTER TABLE request_engine.webauthn_challenges
    DROP CONSTRAINT webauthn_challenges_scope_check;
ALTER TABLE request_engine.webauthn_challenges
    ADD CONSTRAINT webauthn_challenges_scope_check
    CHECK ((((((native_identity_id IS NOT NULL))::integer + ((session_id IS NOT NULL))::integer)
        + ((setup_session_id IS NOT NULL))::integer) = 1));
"""

_ORIGINAL_CREATE_CHALLENGE = """
CREATE OR REPLACE FUNCTION request_auth.create_webauthn_challenge(p_challenge_id uuid, p_purpose text, p_native_identity_id uuid, p_session_id uuid, p_setup_session_id uuid, p_challenge_digest bytea, p_expires_at timestamp with time zone) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
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
"""

_EXTENDED_PURPOSE_CHECK = """
ALTER TABLE request_engine.webauthn_challenges
    DROP CONSTRAINT webauthn_challenges_purpose_check;
ALTER TABLE request_engine.webauthn_challenges
    ADD CONSTRAINT webauthn_challenges_purpose_check
    CHECK ((purpose = ANY (ARRAY['registration'::text, 'authentication'::text,
        'step_up'::text, 'authentication_discoverable'::text])));
"""

_EXTENDED_SCOPE_CHECK = """
ALTER TABLE request_engine.webauthn_challenges
    DROP CONSTRAINT webauthn_challenges_scope_check;
ALTER TABLE request_engine.webauthn_challenges
    ADD CONSTRAINT webauthn_challenges_scope_check
    CHECK (
        (((((native_identity_id IS NOT NULL))::integer + ((session_id IS NOT NULL))::integer)
            + ((setup_session_id IS NOT NULL))::integer) = 1)
        OR (purpose = 'authentication_discoverable'::text
            AND native_identity_id IS NULL
            AND session_id IS NULL
            AND setup_session_id IS NULL)
    );
"""

_EXTENDED_CREATE_CHALLENGE = """
CREATE OR REPLACE FUNCTION request_auth.create_webauthn_challenge(p_challenge_id uuid, p_purpose text, p_native_identity_id uuid, p_session_id uuid, p_setup_session_id uuid, p_challenge_digest bytea, p_expires_at timestamp with time zone) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
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
               OR p_purpose NOT IN ('registration', 'authentication', 'step_up',
                                    'authentication_discoverable')
               OR p_expires_at <= clock_timestamp()
               OR (p_purpose = 'authentication_discoverable' AND v_scope_count <> 0)
               OR (p_purpose <> 'authentication_discoverable' AND v_scope_count <> 1)
            THEN
                RETURN false;
            END IF;

            PERFORM pg_advisory_xact_lock(
                hashtextextended(
                    coalesce(p_purpose, '') || '|'
                    || coalesce(p_native_identity_id::text, '') || '|'
                    || coalesce(p_session_id::text, '') || '|'
                    || coalesce(p_setup_session_id::text, ''),
                    0
                )
            );

            -- A discoverable challenge has no scope to serialize per identity, so
            -- it must not expire other operators' live unbound challenges.
            IF p_purpose <> 'authentication_discoverable' THEN
                UPDATE request_engine.webauthn_challenges
                   SET status = 'expired'
                 WHERE status = 'pending'
                   AND purpose = p_purpose
                   AND native_identity_id IS NOT DISTINCT FROM p_native_identity_id
                   AND session_id IS NOT DISTINCT FROM p_session_id
                   AND setup_session_id IS NOT DISTINCT FROM p_setup_session_id;
            END IF;

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

_DISCOVERABLE_FINALIZE = """
CREATE FUNCTION request_auth.finalize_discoverable_webauthn_authentication(
    p_challenge_digest bytea,
    p_credential_row_id uuid,
    p_sign_count bigint,
    p_backup_eligible boolean,
    p_backup_state boolean,
    p_user_verified boolean,
    p_session_id uuid,
    p_token_digest bytea,
    p_token_fingerprint text,
    p_expires_at timestamp with time zone
) RETURNS TABLE(native_identity_id uuid)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
        DECLARE
            v_challenge request_engine.webauthn_challenges%ROWTYPE;
            v_identity uuid;
            v_epoch bigint;
            v_identity_status text;
            v_credential_identity uuid;
            v_credential_status text;
        BEGIN
            IF p_challenge_digest IS NULL
               OR octet_length(p_challenge_digest) <> 32
               OR p_credential_row_id IS NULL
               OR p_sign_count < 0
               OR p_session_id IS NULL
               OR p_token_digest IS NULL
               OR octet_length(p_token_digest) <> 32
               OR p_token_fingerprint IS NULL
               OR p_token_fingerprint !~ '^[0-9a-f]{16}$'
               OR p_expires_at IS NULL
            THEN
                RETURN;
            END IF;

            SELECT challenge.* INTO v_challenge
              FROM request_engine.webauthn_challenges AS challenge
             WHERE challenge.challenge_digest = p_challenge_digest
               AND challenge.purpose = 'authentication_discoverable'
               AND challenge.status = 'pending'
               AND challenge.expires_at > clock_timestamp()
               AND challenge.native_identity_id IS NULL
               AND challenge.session_id IS NULL
               AND challenge.setup_session_id IS NULL
             FOR UPDATE;
            IF NOT FOUND THEN RETURN; END IF;

            -- Resolve the owning identity from the presented credential. The
            -- caller never supplies an identity; this read only selects the row.
            SELECT credential.native_identity_id INTO v_identity
              FROM request_engine.webauthn_credentials AS credential
             WHERE credential.id = p_credential_row_id;
            IF NOT FOUND OR v_identity IS NULL THEN RETURN; END IF;

            -- Same lock order as finalize_webauthn_authentication:
            -- authority -> identity -> credential.
            PERFORM 1
              FROM request_engine.identity_authorities AS authority
              JOIN request_engine.native_identities AS native_identity
                ON native_identity.identity_authority_id = authority.id
             WHERE native_identity.id = v_identity
               AND authority.kind = 'native' AND authority.status = 'active'
             FOR SHARE OF authority;
            IF NOT FOUND THEN RETURN; END IF;

            SELECT session_epoch, status
              INTO v_epoch, v_identity_status
              FROM request_engine.native_identities
             WHERE id = v_identity
             FOR UPDATE;
            IF NOT FOUND OR v_identity_status <> 'active' THEN
                RETURN;
            END IF;

            SELECT credential.native_identity_id, credential.status
              INTO v_credential_identity, v_credential_status
              FROM request_engine.webauthn_credentials AS credential
             WHERE credential.id = p_credential_row_id
             FOR UPDATE;
            IF NOT FOUND OR v_credential_status <> 'active'
               OR v_credential_identity <> v_identity
            THEN
                RETURN;
            END IF;
            IF p_expires_at <= clock_timestamp() THEN
                RETURN;
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
                p_session_id, v_identity, NULL, p_credential_row_id,
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

            RETURN QUERY SELECT v_identity;
        END
        $$;
"""


def upgrade() -> None:
    op.execute(_EXTENDED_PURPOSE_CHECK)
    op.execute(_EXTENDED_SCOPE_CHECK)
    op.execute(_EXTENDED_CREATE_CHALLENGE)
    op.execute(_DISCOVERABLE_FINALIZE)
    op.execute(
        "ALTER FUNCTION request_auth.finalize_discoverable_webauthn_authentication("
        + _DISCOVERABLE_FINALIZE_SIGNATURE
        + ") OWNER TO request_engine_schema_owner;"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION request_auth.finalize_discoverable_webauthn_authentication("
        + _DISCOVERABLE_FINALIZE_SIGNATURE
        + ") FROM PUBLIC;"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION request_auth.finalize_discoverable_webauthn_authentication("
        + _DISCOVERABLE_FINALIZE_SIGNATURE
        + ") TO request_engine_app;"
    )


def downgrade() -> None:
    op.execute(
        "DROP FUNCTION request_auth.finalize_discoverable_webauthn_authentication("
        + _DISCOVERABLE_FINALIZE_SIGNATURE
        + ");"
    )
    op.execute(_ORIGINAL_CREATE_CHALLENGE)
    op.execute(_ORIGINAL_PURPOSE_CHECK)
    op.execute(_ORIGINAL_SCOPE_CHECK)
