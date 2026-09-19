"""Harden Native auth state transitions and authority invalidation.

Revision ID: 0010_native_auth_guards
Revises: 0009_native_auth_runtime
Create Date: 2026-09-08
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010_native_auth_guards"
down_revision: str | Sequence[str] | None = "0009_native_auth_runtime"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION request_engine.guard_native_identity()
        RETURNS trigger LANGUAGE plpgsql
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
        DECLARE
            v_authority_kind text;
            v_authority_status text;
        BEGIN
            SELECT kind, status INTO v_authority_kind, v_authority_status
              FROM request_engine.identity_authorities
             WHERE id = NEW.identity_authority_id;
            IF NOT FOUND OR v_authority_kind <> 'native' THEN
                RAISE EXCEPTION 'Native identity requires a Native identity authority'
                    USING ERRCODE = '23514';
            END IF;
            IF TG_OP = 'INSERT' THEN
                IF v_authority_status <> 'active' THEN
                    RAISE EXCEPTION 'Native identity authority must be active'
                        USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END IF;

            IF ROW(NEW.id, NEW.identity_authority_id, NEW.login_handle, NEW.created_at)
               IS DISTINCT FROM
               ROW(OLD.id, OLD.identity_authority_id, OLD.login_handle, OLD.created_at)
            THEN
                RAISE EXCEPTION 'Native identity and login handle are immutable'
                    USING ERRCODE = '55000';
            END IF;
            IF OLD.status <> 'active' THEN
                RAISE EXCEPTION 'Disabled Native identity is terminal'
                    USING ERRCODE = '55000';
            END IF;
            IF NEW.status = 'disabled' THEN
                IF NEW.revision <> OLD.revision + 1
                   OR NEW.session_epoch <> OLD.session_epoch + 1
                   OR NEW.disabled_at IS NULL
                THEN
                    RAISE EXCEPTION 'Invalid Native identity disable transition'
                        USING ERRCODE = '55000';
                END IF;
                RETURN NEW;
            END IF;
            IF NEW.status = 'active'
               AND NEW.revision = OLD.revision + 1
               AND NEW.session_epoch = OLD.session_epoch + 1
               AND NEW.disabled_at IS NULL
            THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'Invalid Native identity mutation' USING ERRCODE = '55000';
        END
        $$;
        ALTER FUNCTION request_engine.guard_native_identity()
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_engine.guard_native_identity() FROM PUBLIC;
        CREATE TRIGGER native_identities_guard
            BEFORE INSERT OR UPDATE ON request_engine.native_identities
            FOR EACH ROW EXECUTE FUNCTION request_engine.guard_native_identity();

        CREATE FUNCTION request_engine.guard_native_credential()
        RETURNS trigger LANGUAGE plpgsql
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                RETURN NEW;
            END IF;
            IF ROW(NEW.id, NEW.native_identity_id, NEW.kind, NEW.verifier, NEW.created_at)
               IS DISTINCT FROM
               ROW(OLD.id, OLD.native_identity_id, OLD.kind, OLD.verifier, OLD.created_at)
            THEN
                RAISE EXCEPTION 'Native credential identity and verifier are immutable'
                    USING ERRCODE = '55000';
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
        CREATE TRIGGER native_credentials_guard
            BEFORE INSERT OR UPDATE ON request_engine.native_credentials
            FOR EACH ROW EXECUTE FUNCTION request_engine.guard_native_credential();

        CREATE FUNCTION request_engine.guard_native_session()
        RETURNS trigger LANGUAGE plpgsql
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                RETURN NEW;
            END IF;
            IF ROW(NEW.id, NEW.native_identity_id, NEW.credential_id, NEW.token_digest,
                   NEW.token_fingerprint, NEW.session_epoch, NEW.created_at, NEW.expires_at)
               IS DISTINCT FROM
               ROW(OLD.id, OLD.native_identity_id, OLD.credential_id, OLD.token_digest,
                   OLD.token_fingerprint, OLD.session_epoch, OLD.created_at, OLD.expires_at)
            THEN
                RAISE EXCEPTION 'Native session credential material is immutable'
                    USING ERRCODE = '55000';
            END IF;
            IF NEW.status = OLD.status
               AND NEW.revoked_at IS NOT DISTINCT FROM OLD.revoked_at
               AND NEW.revocation_reason IS NOT DISTINCT FROM OLD.revocation_reason
               AND (OLD.last_seen_at IS NULL OR NEW.last_seen_at >= OLD.last_seen_at)
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
        CREATE TRIGGER native_sessions_guard
            BEFORE INSERT OR UPDATE ON request_engine.native_sessions
            FOR EACH ROW EXECUTE FUNCTION request_engine.guard_native_session();

        CREATE FUNCTION request_engine.guard_native_recovery_intent()
        RETURNS trigger LANGUAGE plpgsql
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                RETURN NEW;
            END IF;
            IF ROW(NEW.id, NEW.native_identity_id, NEW.token_digest, NEW.token_fingerprint,
                   NEW.created_at, NEW.expires_at)
               IS DISTINCT FROM
               ROW(OLD.id, OLD.native_identity_id, OLD.token_digest, OLD.token_fingerprint,
                   OLD.created_at, OLD.expires_at)
            THEN
                RAISE EXCEPTION 'Native recovery credential material is immutable'
                    USING ERRCODE = '55000';
            END IF;
            IF OLD.status = 'pending'
               AND (
                   (NEW.status = 'consumed' AND NEW.consumed_at IS NOT NULL
                    AND NEW.revoked_at IS NULL)
                   OR
                   (NEW.status = 'revoked' AND NEW.revoked_at IS NOT NULL
                    AND NEW.consumed_at IS NULL)
               )
            THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'Invalid Native recovery mutation' USING ERRCODE = '55000';
        END
        $$;
        ALTER FUNCTION request_engine.guard_native_recovery_intent()
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_engine.guard_native_recovery_intent() FROM PUBLIC;
        CREATE TRIGGER native_recovery_intents_guard
            BEFORE INSERT OR UPDATE ON request_engine.native_recovery_intents
            FOR EACH ROW EXECUTE FUNCTION request_engine.guard_native_recovery_intent();
        """
    )
    op.execute("DROP FUNCTION request_auth.read_native_session(uuid)")
    op.execute(
        """
        CREATE FUNCTION request_auth.read_native_session(p_session_id uuid)
        RETURNS TABLE (
            session_id uuid,
            native_identity_id uuid,
            identity_authority_id uuid,
            credential_id uuid,
            token_digest bytea,
            session_epoch bigint,
            current_session_epoch bigint,
            session_status text,
            identity_status text,
            credential_status text,
            authority_status text,
            expires_at timestamptz
        )
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
            SELECT s.id,
                   s.native_identity_id,
                   i.identity_authority_id,
                   s.credential_id,
                   s.token_digest,
                   s.session_epoch,
                   i.session_epoch,
                   s.status,
                   i.status,
                   c.status,
                   a.status,
                   s.expires_at
              FROM request_engine.native_sessions AS s
              JOIN request_engine.native_identities AS i
                ON i.id = s.native_identity_id
              JOIN request_engine.native_credentials AS c
                ON c.id = s.credential_id
               AND c.native_identity_id = s.native_identity_id
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


def downgrade() -> None:
    op.execute("DROP FUNCTION request_auth.read_native_session(uuid)")
    op.execute(
        """
        CREATE FUNCTION request_auth.read_native_session(p_session_id uuid)
        RETURNS TABLE (
            session_id uuid,
            native_identity_id uuid,
            identity_authority_id uuid,
            credential_id uuid,
            token_digest bytea,
            session_epoch bigint,
            current_session_epoch bigint,
            session_status text,
            identity_status text,
            credential_status text,
            expires_at timestamptz
        )
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
            SELECT s.id, s.native_identity_id, i.identity_authority_id, s.credential_id,
                   s.token_digest, s.session_epoch, i.session_epoch, s.status, i.status,
                   c.status, s.expires_at
              FROM request_engine.native_sessions AS s
              JOIN request_engine.native_identities AS i ON i.id = s.native_identity_id
              JOIN request_engine.native_credentials AS c
                ON c.id = s.credential_id AND c.native_identity_id = s.native_identity_id
             WHERE s.id = p_session_id
        $$;
        ALTER FUNCTION request_auth.read_native_session(uuid)
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_auth.read_native_session(uuid) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_auth.read_native_session(uuid) TO request_engine_app;
        DROP TRIGGER native_recovery_intents_guard ON request_engine.native_recovery_intents;
        DROP FUNCTION request_engine.guard_native_recovery_intent();
        DROP TRIGGER native_sessions_guard ON request_engine.native_sessions;
        DROP FUNCTION request_engine.guard_native_session();
        DROP TRIGGER native_credentials_guard ON request_engine.native_credentials;
        DROP FUNCTION request_engine.guard_native_credential();
        DROP TRIGGER native_identities_guard ON request_engine.native_identities;
        DROP FUNCTION request_engine.guard_native_identity();
        """
    )
