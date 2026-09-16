"""Native-session reauthentication freshness (plan D2 prerequisite).

Adds ``last_authenticated_at`` as the freshness basis for self-service identity
linking: it records the most recent successful credential authentication on a
session, is initialised to ``created_at`` and refreshed only by the new
``request_auth.reauthenticate_native_session`` boundary. ``last_seen_at`` remains
activity time. ADR 0013 sets the accepted reauthentication proof at <= 5 minutes.

The session guard is re-emitted so monotonic ``last_authenticated_at`` updates are
permitted without a status change, while regression and every other immutability
rule are preserved. The auth read boundary exposes the three timestamps.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0048_native_reauth_freshness"
down_revision: str | Sequence[str] | None = "0047_native_identity_disable"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(
        """
        ALTER TABLE request_engine.native_sessions
            ADD COLUMN last_authenticated_at timestamptz;
        UPDATE request_engine.native_sessions
           SET last_authenticated_at = created_at
         WHERE last_authenticated_at IS NULL;
        ALTER TABLE request_engine.native_sessions
            ALTER COLUMN last_authenticated_at SET NOT NULL;
        ALTER TABLE request_engine.native_sessions
            ALTER COLUMN last_authenticated_at SET DEFAULT clock_timestamp();
        """
    )
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
                   s.credential_id,
                   s.token_digest,
                   s.session_epoch,
                   i.session_epoch,
                   s.status,
                   i.status,
                   c.status,
                   a.status,
                   s.expires_at,
                   s.created_at,
                   s.last_seen_at,
                   s.last_authenticated_at
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
    op.execute(
        r"""
        CREATE FUNCTION request_auth.read_native_credential_verifier(
            p_credential_id uuid
        ) RETURNS text
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
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
        ALTER FUNCTION request_auth.read_native_credential_verifier(uuid)
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_auth.read_native_credential_verifier(uuid)
            FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_auth.read_native_credential_verifier(uuid)
            TO request_engine_app;

        CREATE FUNCTION request_auth.reauthenticate_native_session(
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
               AND session.credential_id = p_credential_id
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
        ALTER FUNCTION request_auth.reauthenticate_native_session(uuid, uuid)
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_auth.reauthenticate_native_session(uuid, uuid)
            FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_auth.reauthenticate_native_session(uuid, uuid)
            TO request_engine_app;
        """
    )


def downgrade() -> None:
    raise RuntimeError("Do not remove native-session reauthentication freshness; roll forward")
