"""Add first-party workload bearer credential persistence and read boundary.

Revision ID: 0023_workload_auth
Revises: 0022_staff_transition_scope
Create Date: 2026-09-08

Workload credentials authenticate AGENT/INTEGRATION/SYSTEM subjects only. They
carry no tenant, Principal id, capability, Representation or delegation state.
Only one-way bearer-secret digests are persisted.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0023_workload_auth"
down_revision: str | Sequence[str] | None = "0022_staff_transition_scope"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE request_engine.workload_identities (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            identity_authority_id uuid NOT NULL
                REFERENCES request_engine.identity_authorities(id),
            workload_kind text NOT NULL,
            status text NOT NULL DEFAULT 'active',
            revision bigint NOT NULL DEFAULT 1,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            disabled_at timestamptz,
            CONSTRAINT workload_identities_kind_check
                CHECK (workload_kind IN ('agent', 'integration', 'system')),
            CONSTRAINT workload_identities_status_check
                CHECK (status IN ('active', 'disabled')),
            CONSTRAINT workload_identities_revision_check CHECK (revision > 0),
            CONSTRAINT workload_identities_disabled_check CHECK (
                (status = 'disabled' AND disabled_at IS NOT NULL)
                OR (status = 'active' AND disabled_at IS NULL)
            )
        );
        ALTER TABLE request_engine.workload_identities
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON request_engine.workload_identities FROM PUBLIC;

        CREATE TABLE request_engine.workload_credentials (
            id uuid PRIMARY KEY,
            workload_identity_id uuid NOT NULL
                REFERENCES request_engine.workload_identities(id),
            token_digest bytea NOT NULL,
            token_fingerprint text NOT NULL,
            status text NOT NULL DEFAULT 'active',
            revision bigint NOT NULL DEFAULT 1,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            expires_at timestamptz NOT NULL,
            last_used_at timestamptz,
            revoked_at timestamptz,
            CONSTRAINT workload_credentials_digest_check
                CHECK (octet_length(token_digest) = 32),
            CONSTRAINT workload_credentials_fingerprint_check
                CHECK (token_fingerprint ~ '^[0-9a-f]{16}$'),
            CONSTRAINT workload_credentials_status_check
                CHECK (status IN ('active', 'revoked')),
            CONSTRAINT workload_credentials_revision_check CHECK (revision > 0),
            CONSTRAINT workload_credentials_expiry_check CHECK (expires_at > created_at),
            CONSTRAINT workload_credentials_revocation_check CHECK (
                (status = 'revoked' AND revoked_at IS NOT NULL)
                OR (status = 'active' AND revoked_at IS NULL)
            )
        );
        CREATE UNIQUE INDEX workload_credentials_token_digest_uq
            ON request_engine.workload_credentials (token_digest);
        CREATE INDEX workload_credentials_identity_active_idx
            ON request_engine.workload_credentials (workload_identity_id, expires_at)
            WHERE status = 'active';
        ALTER TABLE request_engine.workload_credentials
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON request_engine.workload_credentials FROM PUBLIC;
        """
    )
    op.execute(
        """
        CREATE FUNCTION request_engine.guard_workload_identity()
        RETURNS trigger LANGUAGE plpgsql
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $$
        DECLARE
            v_authority_kind text;
            v_authority_status text;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Workload identities are append-preserving'
                    USING ERRCODE = '55000';
            END IF;
            SELECT kind, status
              INTO v_authority_kind, v_authority_status
              FROM request_engine.identity_authorities
             WHERE id = NEW.identity_authority_id;
            IF NOT FOUND OR v_authority_kind <> 'workload' THEN
                RAISE EXCEPTION 'Workload identity requires workload authority'
                    USING ERRCODE = '23514';
            END IF;
            IF TG_OP = 'INSERT' THEN
                IF NEW.status = 'active' AND v_authority_status <> 'active' THEN
                    RAISE EXCEPTION 'Active workload identity requires active authority'
                        USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END IF;
            IF ROW(NEW.identity_authority_id, NEW.workload_kind, NEW.created_at)
               IS DISTINCT FROM
               ROW(OLD.identity_authority_id, OLD.workload_kind, OLD.created_at)
            THEN
                RAISE EXCEPTION 'Workload identity facts are immutable'
                    USING ERRCODE = '55000';
            END IF;
            IF OLD.status = NEW.status THEN
                IF NEW.revision <> OLD.revision
                   OR NEW.disabled_at IS DISTINCT FROM OLD.disabled_at
                   OR NEW.updated_at < OLD.updated_at
                THEN
                    RAISE EXCEPTION 'Invalid workload identity update'
                        USING ERRCODE = '55000';
                END IF;
                RETURN NEW;
            END IF;
            IF OLD.status <> 'active' OR NEW.status <> 'disabled'
               OR NEW.revision <> OLD.revision + 1
               OR NEW.disabled_at IS NULL
            THEN
                RAISE EXCEPTION 'Invalid workload identity transition'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END
        $$;
        ALTER FUNCTION request_engine.guard_workload_identity()
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_engine.guard_workload_identity() FROM PUBLIC;
        CREATE TRIGGER workload_identities_guard
            BEFORE INSERT OR UPDATE OR DELETE ON request_engine.workload_identities
            FOR EACH ROW EXECUTE FUNCTION request_engine.guard_workload_identity();

        CREATE FUNCTION request_engine.guard_workload_credential()
        RETURNS trigger LANGUAGE plpgsql
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $$
        DECLARE
            v_identity_active boolean;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Workload credentials are append-preserving'
                    USING ERRCODE = '55000';
            END IF;
            SELECT status = 'active'
              INTO v_identity_active
              FROM request_engine.workload_identities
             WHERE id = NEW.workload_identity_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Workload identity does not exist'
                    USING ERRCODE = '23514';
            END IF;
            IF TG_OP = 'INSERT' THEN
                IF NEW.status = 'active' AND NOT v_identity_active THEN
                    RAISE EXCEPTION 'Active credential requires active workload identity'
                        USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END IF;
            IF ROW(
                NEW.workload_identity_id,
                NEW.token_digest,
                NEW.token_fingerprint,
                NEW.created_at,
                NEW.expires_at
            ) IS DISTINCT FROM ROW(
                OLD.workload_identity_id,
                OLD.token_digest,
                OLD.token_fingerprint,
                OLD.created_at,
                OLD.expires_at
            ) THEN
                RAISE EXCEPTION 'Workload credential identity is immutable'
                    USING ERRCODE = '55000';
            END IF;
            IF OLD.status = NEW.status THEN
                IF NEW.revision <> OLD.revision
                   OR NEW.revoked_at IS DISTINCT FROM OLD.revoked_at
                   OR (
                       OLD.last_used_at IS NOT NULL
                       AND (NEW.last_used_at IS NULL OR NEW.last_used_at < OLD.last_used_at)
                   )
                THEN
                    RAISE EXCEPTION 'Invalid workload credential update'
                        USING ERRCODE = '55000';
                END IF;
                RETURN NEW;
            END IF;
            IF OLD.status <> 'active' OR NEW.status <> 'revoked'
               OR NEW.revision <> OLD.revision + 1
               OR NEW.revoked_at IS NULL
            THEN
                RAISE EXCEPTION 'Invalid workload credential transition'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END
        $$;
        ALTER FUNCTION request_engine.guard_workload_credential()
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_engine.guard_workload_credential() FROM PUBLIC;
        CREATE TRIGGER workload_credentials_guard
            BEFORE INSERT OR UPDATE OR DELETE ON request_engine.workload_credentials
            FOR EACH ROW EXECUTE FUNCTION request_engine.guard_workload_credential();
        """
    )
    op.execute(
        """
        CREATE FUNCTION request_auth.read_workload_credential(p_credential_id uuid)
        RETURNS TABLE (
            credential_id uuid,
            workload_identity_id uuid,
            identity_authority_id uuid,
            workload_kind text,
            token_digest bytea,
            credential_status text,
            identity_status text,
            authority_status text,
            expires_at timestamptz
        )
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
        ALTER FUNCTION request_auth.read_workload_credential(uuid)
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_auth.read_workload_credential(uuid) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_auth.read_workload_credential(uuid)
            TO request_engine_app;
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION request_auth.read_workload_credential(uuid)")
    op.execute("DROP TABLE request_engine.workload_credentials CASCADE")
    op.execute("DROP FUNCTION request_engine.guard_workload_credential()")
    op.execute("DROP TABLE request_engine.workload_identities CASCADE")
    op.execute("DROP FUNCTION request_engine.guard_workload_identity()")
