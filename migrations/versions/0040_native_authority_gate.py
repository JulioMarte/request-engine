"""Suspend positive Native authentication mutations with their identity authority.

Authority SHARE precedes identity and proof locks; restrictive revocation remains
available. Existing function signatures, owners and EXECUTE ACLs are preserved.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0040_native_authority_gate"
down_revision: str | Sequence[str] | None = "0039_native_recovery_lock_order"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    # Explicit replacement bodies are independent of live catalog text/history imports.
    op.execute("""
        CREATE OR REPLACE FUNCTION request_auth.read_native_password_credential(
            p_identity_authority_id uuid,
            p_login_handle text
        )
        RETURNS TABLE (
            native_identity_id uuid,
            credential_id uuid,
            verifier text,
            identity_status text,
            credential_status text,
            session_epoch bigint,
            identity_revision bigint,
            credential_revision bigint
        )
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
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

        CREATE OR REPLACE FUNCTION request_auth.lock_credentialed_native_identity(
            p_identity_authority_id uuid,
            p_native_identity_id uuid
        ) RETURNS boolean
        LANGUAGE plpgsql
        SECURITY DEFINER
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

        CREATE OR REPLACE FUNCTION request_auth.create_native_identity(
            p_identity_authority_id uuid,
            p_native_identity_id uuid,
            p_login_handle text,
            p_credential_id uuid,
            p_verifier text
        ) RETURNS boolean
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
        DECLARE
            v_identity_id uuid;
        BEGIN
            PERFORM 1
              FROM request_engine.identity_authorities
             WHERE id = p_identity_authority_id
               AND status = 'active' AND kind = 'native'
             FOR SHARE;
            IF NOT FOUND THEN
                RETURN false;
            END IF;

            INSERT INTO request_engine.native_identities (
                id, identity_authority_id, login_handle
            ) VALUES (
                p_native_identity_id, p_identity_authority_id, p_login_handle
            )
            ON CONFLICT (identity_authority_id, login_handle) DO NOTHING
            RETURNING id INTO v_identity_id;
            IF v_identity_id IS NULL THEN
                RETURN false;
            END IF;

            INSERT INTO request_engine.native_credentials (
                id, native_identity_id, verifier
            ) VALUES (
                p_credential_id, p_native_identity_id, p_verifier
            );
            RETURN true;
        END
        $$;

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
            -- Authority is locked before identity; SHARE conflicts with status UPDATE.
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
                id,
                native_identity_id,
                credential_id,
                token_digest,
                token_fingerprint,
                session_epoch,
                expires_at
            ) VALUES (
                p_session_id,
                p_native_identity_id,
                p_credential_id,
                p_token_digest,
                p_token_fingerprint,
                v_epoch,
                p_expires_at
            );
            UPDATE request_engine.native_credentials
               SET last_used_at = clock_timestamp()
             WHERE id = p_credential_id;
            RETURN true;
        END
        $$;

        CREATE OR REPLACE FUNCTION request_auth.rotate_native_password(
            p_native_identity_id uuid,
            p_expected_credential_id uuid,
            p_new_credential_id uuid,
            p_new_verifier text,
            p_reason text
        ) RETURNS boolean
        LANGUAGE plpgsql
        SECURITY DEFINER
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

        CREATE OR REPLACE FUNCTION request_auth.create_native_recovery_intent(
            p_native_identity_id uuid,
            p_recovery_id uuid,
            p_token_digest bytea,
            p_token_fingerprint text,
            p_expires_at timestamptz
        ) RETURNS boolean
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
        DECLARE
            v_status text;
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

            SELECT status INTO v_status
              FROM request_engine.native_identities
             WHERE id = p_native_identity_id
             FOR UPDATE;
            IF NOT FOUND OR v_status <> 'active' OR p_expires_at <= clock_timestamp() THEN
                RETURN false;
            END IF;
            UPDATE request_engine.native_recovery_intents
               SET status = 'revoked',
                   revoked_at = clock_timestamp()
             WHERE native_identity_id = p_native_identity_id
               AND status = 'pending';
            INSERT INTO request_engine.native_recovery_intents (
                id,
                native_identity_id,
                token_digest,
                token_fingerprint,
                expires_at
            ) VALUES (
                p_recovery_id,
                p_native_identity_id,
                p_token_digest,
                p_token_fingerprint,
                p_expires_at
            );
            RETURN true;
        END
        $$;

        CREATE OR REPLACE FUNCTION request_auth.consume_native_recovery_intent(
            p_recovery_id uuid, p_token_digest bytea,
            p_new_credential_id uuid, p_new_verifier text
        ) RETURNS uuid
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
        DECLARE
            v_native_identity_id uuid;
            v_identity_status text;
        BEGIN
            -- Resolve a candidate without holding an intent lock. Identity is
            -- the credential serialization root, after the authority suspension gate.
            SELECT r.native_identity_id INTO v_native_identity_id
              FROM request_engine.native_recovery_intents r
             WHERE r.id = p_recovery_id AND r.token_digest = p_token_digest
               AND r.status = 'pending' AND r.expires_at > clock_timestamp();
            IF NOT FOUND THEN RETURN NULL; END IF;

            -- Authority is locked before identity; SHARE conflicts with status UPDATE.
            PERFORM 1
              FROM request_engine.identity_authorities AS authority
              JOIN request_engine.native_identities AS native_identity
                ON native_identity.identity_authority_id = authority.id
             WHERE native_identity.id = v_native_identity_id
               AND authority.kind = 'native' AND authority.status = 'active'
             FOR SHARE OF authority;
            IF NOT FOUND THEN RETURN NULL; END IF;

            SELECT i.status INTO v_identity_status
              FROM request_engine.native_identities i
             WHERE i.id = v_native_identity_id
             FOR UPDATE;
            IF NOT FOUND OR v_identity_status <> 'active' THEN RETURN NULL; END IF;

            -- The first read was advisory: expiry, revocation and a competing
            -- successful recovery must be revalidated after the identity lock.
            PERFORM 1 FROM request_engine.native_recovery_intents r
             WHERE r.id = p_recovery_id AND r.native_identity_id = v_native_identity_id
               AND r.token_digest = p_token_digest AND r.status = 'pending'
               AND r.expires_at > clock_timestamp()
             FOR UPDATE;
            IF NOT FOUND THEN RETURN NULL; END IF;

            UPDATE request_engine.native_credentials
               SET status = 'revoked', revision = revision + 1,
                   rotated_at = clock_timestamp(), revoked_at = clock_timestamp()
             WHERE native_identity_id = v_native_identity_id
               AND kind = 'password' AND status = 'active';
            INSERT INTO request_engine.native_credentials (id, native_identity_id, verifier)
                VALUES (p_new_credential_id, v_native_identity_id, p_new_verifier);
            UPDATE request_engine.native_identities
               SET session_epoch = session_epoch + 1, revision = revision + 1,
                   updated_at = clock_timestamp()
             WHERE id = v_native_identity_id;
            UPDATE request_engine.native_sessions
               SET status = 'revoked', revoked_at = clock_timestamp(),
                   revocation_reason = 'credential_recovery'
             WHERE native_identity_id = v_native_identity_id AND status = 'active';
            UPDATE request_engine.native_recovery_intents
               SET status = 'consumed', consumed_at = clock_timestamp()
             WHERE id = p_recovery_id;
            UPDATE request_engine.native_recovery_intents
               SET status = 'revoked', revoked_at = clock_timestamp()
             WHERE native_identity_id = v_native_identity_id
               AND id <> p_recovery_id AND status = 'pending';
            RETURN v_native_identity_id;
        END
        $$;
    """)


def downgrade() -> None:
    raise RuntimeError("Do not reopen Native authority suspension bypasses; roll forward")
