"""Persist WebAuthn credentials and bounded challenge lifecycle.

Revision ID: 0059_webauthn_credentials
Revises: 0058_recovery_operator_read

Implements the P2 durable surface of ADR 0014 §5.5/§5.5.1:

- ``webauthn_credentials`` stores public credential material only (never an
  authenticator private key), with a globally unique credential id so one
  credential can bind to at most one native identity;
- ``webauthn_challenges`` stores challenge digests only, single-purpose,
  single-use and TTL-bounded, scoped to a native identity, session or (later)
  setup session;
- the runtime app login reaches both only through narrow ``request_auth``
  functions, never direct table access.

Session issuance with assurance propagation is a separate slice; this migration
deliberately does not alter ``native_sessions``.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0059_webauthn_credentials"
down_revision: str | Sequence[str] | None = "0058_recovery_operator_read"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RUNTIME = "request_engine_app"
_OWNER = "request_engine_schema_owner"

_FUNCTIONS = (
    "create_webauthn_challenge(uuid, text, uuid, uuid, uuid, bytea, timestamptz)",
    "consume_webauthn_challenge(bytea, text)",
    "register_webauthn_credential("
    "uuid, uuid, bytea, bytea, bigint, text, boolean, boolean, boolean)",
    "read_webauthn_credentials(uuid)",
    "update_webauthn_credential_sign_count(uuid, uuid, bigint)",
    "revoke_webauthn_credential(uuid, uuid, text)",
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(
        """
        CREATE TABLE request_engine.webauthn_credentials (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            native_identity_id uuid NOT NULL
                REFERENCES request_engine.native_identities(id),
            credential_id bytea NOT NULL,
            public_key bytea NOT NULL,
            sign_count bigint NOT NULL DEFAULT 0,
            aaguid text NOT NULL,
            backup_eligible boolean NOT NULL DEFAULT false,
            backup_state boolean NOT NULL DEFAULT false,
            user_verified boolean NOT NULL DEFAULT true,
            status text NOT NULL DEFAULT 'active',
            revision bigint NOT NULL DEFAULT 1,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            last_used_at timestamptz,
            revoked_at timestamptz,
            CONSTRAINT webauthn_credentials_id_check CHECK (
                octet_length(credential_id) BETWEEN 16 AND 1023
            ),
            CONSTRAINT webauthn_credentials_key_check CHECK (octet_length(public_key) > 0),
            CONSTRAINT webauthn_credentials_sign_count_check CHECK (sign_count >= 0),
            CONSTRAINT webauthn_credentials_aaguid_check CHECK (aaguid ~ '^[0-9a-f]{32}$'),
            CONSTRAINT webauthn_credentials_status_check CHECK (status IN ('active', 'revoked')),
            CONSTRAINT webauthn_credentials_revision_check CHECK (revision > 0),
            CONSTRAINT webauthn_credentials_revocation_check CHECK (
                (status = 'revoked' AND revoked_at IS NOT NULL)
                OR (status = 'active' AND revoked_at IS NULL)
            ),
            CONSTRAINT webauthn_credentials_last_used_check CHECK (
                last_used_at IS NULL OR last_used_at >= created_at
            ),
            UNIQUE (credential_id)
        );
        CREATE INDEX webauthn_credentials_identity_active_idx
            ON request_engine.webauthn_credentials (native_identity_id)
            WHERE status = 'active';
        ALTER TABLE request_engine.webauthn_credentials OWNER TO request_engine_schema_owner;
        REVOKE ALL ON request_engine.webauthn_credentials FROM PUBLIC;

        CREATE TABLE request_engine.webauthn_challenges (
            id uuid PRIMARY KEY,
            purpose text NOT NULL,
            native_identity_id uuid REFERENCES request_engine.native_identities(id),
            session_id uuid,
            setup_session_id uuid REFERENCES request_engine.setup_sessions(id),
            challenge_digest bytea NOT NULL,
            status text NOT NULL DEFAULT 'pending',
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            expires_at timestamptz NOT NULL,
            consumed_at timestamptz,
            CONSTRAINT webauthn_challenges_purpose_check CHECK (
                purpose IN ('registration', 'authentication')
            ),
            CONSTRAINT webauthn_challenges_digest_check CHECK (
                octet_length(challenge_digest) = 32
            ),
            CONSTRAINT webauthn_challenges_status_check CHECK (
                status IN ('pending', 'consumed', 'expired')
            ),
            CONSTRAINT webauthn_challenges_expiry_check CHECK (expires_at > created_at),
            CONSTRAINT webauthn_challenges_scope_check CHECK (
                (
                    (native_identity_id IS NOT NULL)::int
                    + (session_id IS NOT NULL)::int
                    + (setup_session_id IS NOT NULL)::int
                ) = 1
            ),
            CONSTRAINT webauthn_challenges_terminal_check CHECK (
                (status = 'pending' AND consumed_at IS NULL)
                OR (status = 'consumed' AND consumed_at IS NOT NULL)
                OR (status = 'expired' AND consumed_at IS NULL)
            ),
            UNIQUE (challenge_digest)
        );
        CREATE INDEX webauthn_challenges_scope_pending_idx
            ON request_engine.webauthn_challenges (purpose, expires_at)
            WHERE status = 'pending';
        ALTER TABLE request_engine.webauthn_challenges OWNER TO request_engine_schema_owner;
        REVOKE ALL ON request_engine.webauthn_challenges FROM PUBLIC;
        """
    )

    # Disabling a native identity must revoke its WebAuthn credentials as well.
    op.execute(
        r"""
        CREATE FUNCTION request_engine.revoke_webauthn_credentials_on_disable()
        RETURNS trigger LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $$
        BEGIN
            IF NEW.status = 'disabled' AND OLD.status <> 'disabled' THEN
                UPDATE request_engine.webauthn_credentials
                   SET status = 'revoked',
                       revision = revision + 1,
                       revoked_at = clock_timestamp()
                 WHERE native_identity_id = NEW.id
                   AND status = 'active';
            END IF;
            RETURN NEW;
        END
        $$;
        ALTER FUNCTION request_engine.revoke_webauthn_credentials_on_disable()
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_engine.revoke_webauthn_credentials_on_disable()
            FROM PUBLIC;
        CREATE TRIGGER native_identities_revoke_webauthn_credentials
            AFTER UPDATE ON request_engine.native_identities
            FOR EACH ROW EXECUTE FUNCTION request_engine.revoke_webauthn_credentials_on_disable();
        """
    )

    op.execute(
        r"""
        CREATE FUNCTION request_auth.create_webauthn_challenge(
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
               OR p_purpose NOT IN ('registration', 'authentication')
               OR v_scope_count <> 1
               OR p_expires_at <= clock_timestamp()
            THEN
                RETURN false;
            END IF;

            -- At most one live challenge per scope and purpose.
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

        CREATE FUNCTION request_auth.consume_webauthn_challenge(
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
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
        DECLARE
            v_row request_engine.webauthn_challenges%ROWTYPE;
        BEGIN
            IF p_challenge_digest IS NULL OR octet_length(p_challenge_digest) <> 32 THEN
                RETURN;
            END IF;
            SELECT challenge.* INTO v_row
              FROM request_engine.webauthn_challenges AS challenge
             WHERE challenge.challenge_digest = p_challenge_digest
               AND challenge.purpose = p_purpose
               AND challenge.status = 'pending'
               AND challenge.expires_at > clock_timestamp()
             FOR UPDATE;
            IF NOT FOUND THEN
                RETURN;
            END IF;
            UPDATE request_engine.webauthn_challenges
               SET status = 'consumed',
                   consumed_at = clock_timestamp()
             WHERE id = v_row.id;
            RETURN QUERY SELECT
                v_row.id,
                v_row.native_identity_id,
                v_row.session_id,
                v_row.setup_session_id,
                v_row.expires_at;
        END
        $$;

        CREATE FUNCTION request_auth.register_webauthn_credential(
            p_credential_id uuid,
            p_native_identity_id uuid,
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
            v_identity_status text;
        BEGIN
            IF p_credential_id IS NULL
               OR p_native_identity_id IS NULL
               OR p_credential_id_bytes IS NULL
               OR p_public_key IS NULL
               OR p_sign_count < 0
               OR p_aaguid IS NULL
            THEN
                RETURN false;
            END IF;

            SELECT status INTO v_identity_status
              FROM request_engine.native_identities
             WHERE id = p_native_identity_id
             FOR UPDATE;
            IF NOT FOUND OR v_identity_status <> 'active' THEN
                RETURN false;
            END IF;

            INSERT INTO request_engine.webauthn_credentials (
                id, native_identity_id, credential_id, public_key, sign_count,
                aaguid, backup_eligible, backup_state, user_verified
            ) VALUES (
                p_credential_id, p_native_identity_id, p_credential_id_bytes,
                p_public_key, p_sign_count, p_aaguid, p_backup_eligible,
                p_backup_state, p_user_verified
            )
            ON CONFLICT (credential_id) DO NOTHING;
            RETURN FOUND;
        END
        $$;

        CREATE FUNCTION request_auth.read_webauthn_credentials(
            p_native_identity_id uuid
        )
        RETURNS TABLE (
            id uuid,
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

        CREATE FUNCTION request_auth.update_webauthn_credential_sign_count(
            p_credential_id uuid,
            p_native_identity_id uuid,
            p_new_sign_count bigint
        ) RETURNS boolean
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
        DECLARE
            v_updated bigint;
        BEGIN
            IF p_new_sign_count < 0 THEN
                RETURN false;
            END IF;
            UPDATE request_engine.webauthn_credentials
               SET sign_count = p_new_sign_count,
                   last_used_at = clock_timestamp()
             WHERE id = p_credential_id
               AND native_identity_id = p_native_identity_id
               AND status = 'active';
            GET DIAGNOSTICS v_updated = ROW_COUNT;
            RETURN v_updated > 0;
        END
        $$;

        CREATE FUNCTION request_auth.revoke_webauthn_credential(
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
            RETURN v_updated > 0;
        END
        $$;
        """
    )

    for signature in _FUNCTIONS:
        op.execute(f"ALTER FUNCTION request_auth.{signature} OWNER TO {_OWNER}")
        op.execute(f"REVOKE ALL ON FUNCTION request_auth.{signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION request_auth.{signature} TO {_RUNTIME}")


def downgrade() -> None:
    raise RuntimeError("WebAuthn credential/challenge state is append-preserving; roll forward")
