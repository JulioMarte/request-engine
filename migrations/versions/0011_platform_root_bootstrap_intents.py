"""Persist one-time platform root bootstrap intents and constrain bootstrap provenance.

Revision ID: 0011_platform_root_intent
Revises: 0010_native_auth_guards
Create Date: 2026-09-08

Bootstrap intent secrets are never stored in cleartext. This migration only
establishes the consumable deployment-trust fact; root creation is wired through
a separate narrow command boundary after this state model is PostgreSQL-proven.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011_platform_root_intent"
down_revision: str | Sequence[str] | None = "0010_native_auth_guards"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE request_engine.platform_bootstrap_intents (
            id uuid PRIMARY KEY,
            token_digest bytea NOT NULL,
            token_fingerprint text NOT NULL,
            permitted_action text NOT NULL DEFAULT 'platform.root.establish',
            provenance_reference text NOT NULL,
            status text NOT NULL DEFAULT 'pending',
            revision bigint NOT NULL DEFAULT 1,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            expires_at timestamptz NOT NULL,
            consumed_at timestamptz,
            revoked_at timestamptz,
            CONSTRAINT platform_bootstrap_intents_digest_check
                CHECK (octet_length(token_digest) = 32),
            CONSTRAINT platform_bootstrap_intents_fingerprint_check
                CHECK (token_fingerprint ~ '^[0-9a-f]{16}$'),
            CONSTRAINT platform_bootstrap_intents_action_check
                CHECK (permitted_action = 'platform.root.establish'),
            CONSTRAINT platform_bootstrap_intents_provenance_check
                CHECK (length(btrim(provenance_reference)) BETWEEN 1 AND 500),
            CONSTRAINT platform_bootstrap_intents_status_check
                CHECK (status IN ('pending', 'consumed', 'revoked')),
            CONSTRAINT platform_bootstrap_intents_revision_check CHECK (revision > 0),
            CONSTRAINT platform_bootstrap_intents_expiry_check CHECK (expires_at > created_at),
            CONSTRAINT platform_bootstrap_intents_terminal_check CHECK (
                (status = 'pending' AND consumed_at IS NULL AND revoked_at IS NULL)
                OR (status = 'consumed' AND consumed_at IS NOT NULL AND revoked_at IS NULL)
                OR (status = 'revoked' AND consumed_at IS NULL AND revoked_at IS NOT NULL)
            ),
            UNIQUE (token_digest)
        );
        CREATE INDEX platform_bootstrap_intents_pending_expiry_idx
            ON request_engine.platform_bootstrap_intents (expires_at)
            WHERE status = 'pending';
        ALTER TABLE request_engine.platform_bootstrap_intents
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON request_engine.platform_bootstrap_intents FROM PUBLIC;
        REVOKE ALL ON request_engine.platform_bootstrap_intents FROM request_engine_app;

        ALTER TABLE request_engine.principal_authority_grants
            ADD CONSTRAINT principal_authority_grants_trust_bootstrap_scope_check CHECK (
                provenance_kind <> 'trust_bootstrap'
                OR (
                    principal_plane = 'platform'
                    AND authority_plane = 'platform'
                    AND organization_id IS NULL
                    AND granted_by_principal_id IS NULL
                )
            );
        """
    )
    op.execute(
        """
        CREATE FUNCTION request_engine.guard_platform_bootstrap_intent()
        RETURNS trigger LANGUAGE plpgsql
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Platform bootstrap intents are append-preserving'
                    USING ERRCODE = '55000';
            END IF;
            IF TG_OP = 'INSERT' THEN
                RETURN NEW;
            END IF;
            IF ROW(NEW.id, NEW.token_digest, NEW.token_fingerprint,
                   NEW.permitted_action, NEW.provenance_reference,
                   NEW.created_at, NEW.expires_at)
               IS DISTINCT FROM
               ROW(OLD.id, OLD.token_digest, OLD.token_fingerprint,
                   OLD.permitted_action, OLD.provenance_reference,
                   OLD.created_at, OLD.expires_at)
            THEN
                RAISE EXCEPTION 'Platform bootstrap intent identity is immutable'
                    USING ERRCODE = '55000';
            END IF;
            IF OLD.status <> 'pending' OR NEW.revision <> OLD.revision + 1 THEN
                RAISE EXCEPTION 'Platform bootstrap intent terminal transition is invalid'
                    USING ERRCODE = '55000';
            END IF;
            IF NEW.status = 'consumed'
               AND NEW.consumed_at IS NOT NULL
               AND NEW.revoked_at IS NULL
            THEN
                RETURN NEW;
            END IF;
            IF NEW.status = 'revoked'
               AND NEW.revoked_at IS NOT NULL
               AND NEW.consumed_at IS NULL
            THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'Platform bootstrap intent may only be consumed or revoked'
                USING ERRCODE = '55000';
        END
        $$;
        ALTER FUNCTION request_engine.guard_platform_bootstrap_intent()
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_engine.guard_platform_bootstrap_intent() FROM PUBLIC;
        CREATE TRIGGER platform_bootstrap_intents_guard
            BEFORE INSERT OR UPDATE OR DELETE ON request_engine.platform_bootstrap_intents
            FOR EACH ROW EXECUTE FUNCTION request_engine.guard_platform_bootstrap_intent();
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER platform_bootstrap_intents_guard "
        "ON request_engine.platform_bootstrap_intents"
    )
    op.execute("DROP FUNCTION request_engine.guard_platform_bootstrap_intent()")
    op.execute("DROP TABLE request_engine.platform_bootstrap_intents")
    op.execute(
        "ALTER TABLE request_engine.principal_authority_grants DROP CONSTRAINT "
        "principal_authority_grants_trust_bootstrap_scope_check"
    )
