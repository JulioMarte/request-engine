"""Complete Native HUMAN runtime auth and platform binding read boundaries.

Revision ID: 0009_native_auth_runtime
Revises: 0008_native_auth_read
Create Date: 2026-09-08

The application role never receives direct write privileges on Native credential
state. Password verifiers and one-way token digests cross this boundary; raw
passwords, session tokens and recovery tokens do not.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009_native_auth_runtime"
down_revision: str | Sequence[str] | None = "0008_native_auth_read"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION request_auth.read_native_password_credential(
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
             WHERE i.identity_authority_id = p_identity_authority_id
               AND i.login_handle = p_login_handle
        $$;

        CREATE FUNCTION request_auth.create_native_identity(
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
               AND status = 'active'
             FOR KEY SHARE;
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

        CREATE FUNCTION request_auth.create_native_session(
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

        CREATE FUNCTION request_auth.revoke_native_session(
            p_native_identity_id uuid,
            p_session_id uuid,
            p_reason text
        ) RETURNS boolean
        LANGUAGE plpgsql
        SECURITY DEFINER
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

        CREATE FUNCTION request_auth.revoke_native_sessions(
            p_native_identity_id uuid,
            p_reason text
        ) RETURNS boolean
        LANGUAGE plpgsql
        SECURITY DEFINER
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

        CREATE FUNCTION request_auth.rotate_native_password(
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

        CREATE FUNCTION request_auth.disable_native_identity(
            p_native_identity_id uuid,
            p_reason text
        ) RETURNS boolean
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
        BEGIN
            UPDATE request_engine.native_identities
               SET status = 'disabled',
                   session_epoch = session_epoch + 1,
                   revision = revision + 1,
                   updated_at = clock_timestamp(),
                   disabled_at = clock_timestamp()
             WHERE id = p_native_identity_id
               AND status = 'active';
            IF NOT FOUND THEN
                RETURN false;
            END IF;
            UPDATE request_engine.native_credentials
               SET status = 'revoked',
                   revision = revision + 1,
                   revoked_at = clock_timestamp()
             WHERE native_identity_id = p_native_identity_id
               AND status = 'active';
            UPDATE request_engine.native_sessions
               SET status = 'revoked',
                   revoked_at = clock_timestamp(),
                   revocation_reason = p_reason
             WHERE native_identity_id = p_native_identity_id
               AND status = 'active';
            UPDATE request_engine.native_recovery_intents
               SET status = 'revoked',
                   revoked_at = clock_timestamp()
             WHERE native_identity_id = p_native_identity_id
               AND status = 'pending';
            RETURN true;
        END
        $$;

        CREATE FUNCTION request_auth.create_native_recovery_intent(
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

        CREATE FUNCTION request_auth.consume_native_recovery_intent(
            p_recovery_id uuid,
            p_token_digest bytea,
            p_new_credential_id uuid,
            p_new_verifier text
        ) RETURNS uuid
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
        DECLARE
            v_native_identity_id uuid;
            v_identity_status text;
        BEGIN
            SELECT r.native_identity_id
              INTO v_native_identity_id
              FROM request_engine.native_recovery_intents AS r
             WHERE r.id = p_recovery_id
               AND r.token_digest = p_token_digest
               AND r.status = 'pending'
               AND r.expires_at > clock_timestamp()
             FOR UPDATE;
            IF NOT FOUND THEN
                RETURN NULL;
            END IF;

            SELECT status INTO v_identity_status
              FROM request_engine.native_identities
             WHERE id = v_native_identity_id
             FOR UPDATE;
            IF NOT FOUND OR v_identity_status <> 'active' THEN
                RETURN NULL;
            END IF;

            UPDATE request_engine.native_credentials
               SET status = 'revoked',
                   revision = revision + 1,
                   rotated_at = clock_timestamp(),
                   revoked_at = clock_timestamp()
             WHERE native_identity_id = v_native_identity_id
               AND kind = 'password'
               AND status = 'active';
            INSERT INTO request_engine.native_credentials (
                id, native_identity_id, verifier
            ) VALUES (
                p_new_credential_id, v_native_identity_id, p_new_verifier
            );
            UPDATE request_engine.native_identities
               SET session_epoch = session_epoch + 1,
                   revision = revision + 1,
                   updated_at = clock_timestamp()
             WHERE id = v_native_identity_id;
            UPDATE request_engine.native_sessions
               SET status = 'revoked',
                   revoked_at = clock_timestamp(),
                   revocation_reason = 'credential_recovery'
             WHERE native_identity_id = v_native_identity_id
               AND status = 'active';
            UPDATE request_engine.native_recovery_intents
               SET status = 'consumed',
                   consumed_at = clock_timestamp()
             WHERE id = p_recovery_id;
            UPDATE request_engine.native_recovery_intents
               SET status = 'revoked',
                   revoked_at = clock_timestamp()
             WHERE native_identity_id = v_native_identity_id
               AND id <> p_recovery_id
               AND status = 'pending';
            RETURN v_native_identity_id;
        END
        $$;

        CREATE FUNCTION request_auth.read_platform_identity_bindings(
            p_identity_authority_id uuid,
            p_subject_id text
        )
        RETURNS TABLE (
            binding_id uuid,
            identity_authority_id uuid,
            subject_id text,
            principal_id uuid,
            principal_plane text,
            organization_id uuid,
            status text,
            revision bigint
        )
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine'
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
        """
    )
    signatures = (
        "read_native_password_credential(uuid, text)",
        "create_native_identity(uuid, uuid, text, uuid, text)",
        "create_native_session(uuid, uuid, uuid, bytea, text, timestamptz)",
        "revoke_native_session(uuid, uuid, text)",
        "revoke_native_sessions(uuid, text)",
        "rotate_native_password(uuid, uuid, uuid, text, text)",
        "disable_native_identity(uuid, text)",
        "create_native_recovery_intent(uuid, uuid, bytea, text, timestamptz)",
        "consume_native_recovery_intent(uuid, bytea, uuid, text)",
        "read_platform_identity_bindings(uuid, text)",
    )
    for signature in signatures:
        op.execute(f"ALTER FUNCTION request_auth.{signature} OWNER TO request_engine_schema_owner")
        op.execute(f"REVOKE ALL ON FUNCTION request_auth.{signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION request_auth.{signature} TO request_engine_app")


def downgrade() -> None:
    signatures = (
        "read_platform_identity_bindings(uuid, text)",
        "consume_native_recovery_intent(uuid, bytea, uuid, text)",
        "create_native_recovery_intent(uuid, uuid, bytea, text, timestamptz)",
        "disable_native_identity(uuid, text)",
        "rotate_native_password(uuid, uuid, uuid, text, text)",
        "revoke_native_sessions(uuid, text)",
        "revoke_native_session(uuid, uuid, text)",
        "create_native_session(uuid, uuid, uuid, bytea, text, timestamptz)",
        "create_native_identity(uuid, uuid, text, uuid, text)",
        "read_native_password_credential(uuid, text)",
    )
    for signature in signatures:
        op.execute(f"DROP FUNCTION request_auth.{signature}")
