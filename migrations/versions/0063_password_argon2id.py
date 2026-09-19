"""Versioned Argon2id password verifiers with legacy scrypt compatibility.

Revision ID: 0063_password_argon2id
Revises: 0062_native_session_guard_fix

Implements plan §13:

- the credential verifier CHECK accepts the Argon2id envelope in addition to the
  legacy scrypt format;
- the credential guard permits a controlled verifier-only upgrade (scrypt ->
  Argon2id) while keeping identity, kind, creation time and every status/revision
  transition fail-closed;
- ``rehash_native_password_verifier`` performs the in-place upgrade under the
  native-authority gate, never changing the credential id, revision or sessions,
  so a legacy login is transparently rehashed without forcing a reset.

No mass reset and no forced logout are introduced.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0063_password_argon2id"
down_revision: str | Sequence[str] | None = "0062_native_session_guard_fix"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(
        """
        ALTER TABLE request_engine.native_credentials
            DROP CONSTRAINT native_credentials_verifier_check;
        ALTER TABLE request_engine.native_credentials
            ADD CONSTRAINT native_credentials_verifier_check CHECK (
                length(verifier) > 32
                AND (verifier LIKE 'scrypt$%' OR verifier LIKE '$argon2id$%')
            );
        """
    )
    op.execute(
        r"""
        CREATE OR REPLACE FUNCTION request_engine.guard_native_credential()
        RETURNS trigger LANGUAGE plpgsql
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                RETURN NEW;
            END IF;
            IF ROW(NEW.id, NEW.native_identity_id, NEW.kind, NEW.created_at)
               IS DISTINCT FROM
               ROW(OLD.id, OLD.native_identity_id, OLD.kind, OLD.created_at)
            THEN
                RAISE EXCEPTION 'Native credential identity is immutable'
                    USING ERRCODE = '55000';
            END IF;
            IF NEW.verifier IS DISTINCT FROM OLD.verifier THEN
                -- Only a scrypt -> Argon2id upgrade is permitted, and only as an
                -- isolated verifier change.
                IF NOT (OLD.verifier LIKE 'scrypt$%' AND NEW.verifier LIKE '$argon2id$%') THEN
                    RAISE EXCEPTION 'Native credential verifier may only be upgraded'
                        USING ERRCODE = '55000';
                END IF;
                IF ROW(NEW.status, NEW.revision, NEW.rotated_at, NEW.revoked_at,
                       NEW.last_used_at)
                   IS DISTINCT FROM
                   ROW(OLD.status, OLD.revision, OLD.rotated_at, OLD.revoked_at,
                       OLD.last_used_at)
                THEN
                    RAISE EXCEPTION 'Native credential verifier upgrade must be isolated'
                        USING ERRCODE = '55000';
                END IF;
                RETURN NEW;
            END IF;
            IF NEW.status = OLD.status
               AND NEW.revision = OLD.revision
               AND NEW.rotated_at IS NOT DISTINCT FROM OLD.rotated_at
               AND NEW.revoked_at IS NOT DISTINCT FROM OLD.revoked_at
               AND (OLD.last_used_at IS NULL OR NEW.last_used_at >= OLD.last_used_at)
            THEN
                RETURN NEW;
            END IF;
            IF OLD.status = 'active'
               AND NEW.status = 'revoked'
               AND NEW.revision = OLD.revision + 1
               AND NEW.revoked_at IS NOT NULL
               AND NEW.last_used_at IS NOT DISTINCT FROM OLD.last_used_at
            THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'Invalid Native credential mutation' USING ERRCODE = '55000';
        END
        $$;
        ALTER FUNCTION request_engine.guard_native_credential()
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_engine.guard_native_credential() FROM PUBLIC;

        CREATE FUNCTION request_auth.rehash_native_password_verifier(
            p_credential_id uuid,
            p_native_identity_id uuid,
            p_new_verifier text
        ) RETURNS boolean
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
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
        $$;
        ALTER FUNCTION request_auth.rehash_native_password_verifier(uuid, uuid, text)
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_auth.rehash_native_password_verifier(uuid, uuid, text)
            FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_auth.rehash_native_password_verifier(uuid, uuid, text)
            TO request_engine_app;
        """
    )


def downgrade() -> None:
    raise RuntimeError("Password verifier modernization is append-preserving; roll forward")
