"""Add providerless Native HUMAN credential and session persistence.

Revision ID: 0007_native_human_auth
Revises: 0006_identity_bindings
Create Date: 2026-09-08

Raw passwords, session tokens and recovery tokens are intentionally absent from
this schema. Only password verifier envelopes and one-way token digests cross
the persistence boundary.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007_native_human_auth"
down_revision: str | Sequence[str] | None = "0006_identity_bindings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE request_engine.native_identities (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            identity_authority_id uuid NOT NULL
                REFERENCES request_engine.identity_authorities(id),
            login_handle text NOT NULL,
            status text NOT NULL DEFAULT 'active',
            session_epoch bigint NOT NULL DEFAULT 1,
            revision bigint NOT NULL DEFAULT 1,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            disabled_at timestamptz,
            CONSTRAINT native_identities_handle_check CHECK (login_handle = btrim(login_handle)
                AND length(login_handle) BETWEEN 1 AND 320),
            CONSTRAINT native_identities_status_check CHECK (status IN ('active', 'disabled')),
            CONSTRAINT native_identities_session_epoch_check CHECK (session_epoch > 0),
            CONSTRAINT native_identities_revision_check CHECK (revision > 0),
            CONSTRAINT native_identities_disabled_check CHECK (
                (status = 'disabled' AND disabled_at IS NOT NULL)
                OR (status = 'active' AND disabled_at IS NULL)
            ),
            UNIQUE (identity_authority_id, login_handle)
        );
        ALTER TABLE request_engine.native_identities OWNER TO request_engine_schema_owner;
        REVOKE ALL ON request_engine.native_identities FROM PUBLIC;

        CREATE TABLE request_engine.native_credentials (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            native_identity_id uuid NOT NULL REFERENCES request_engine.native_identities(id),
            kind text NOT NULL DEFAULT 'password',
            verifier text NOT NULL,
            status text NOT NULL DEFAULT 'active',
            revision bigint NOT NULL DEFAULT 1,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            rotated_at timestamptz,
            revoked_at timestamptz,
            last_used_at timestamptz,
            CONSTRAINT native_credentials_kind_check CHECK (kind = 'password'),
            CONSTRAINT native_credentials_verifier_check CHECK (
                length(verifier) > 32 AND verifier LIKE 'scrypt$%'
            ),
            CONSTRAINT native_credentials_status_check CHECK (status IN ('active', 'revoked')),
            CONSTRAINT native_credentials_revision_check CHECK (revision > 0),
            CONSTRAINT native_credentials_revocation_check CHECK (
                (status = 'revoked' AND revoked_at IS NOT NULL)
                OR (status = 'active' AND revoked_at IS NULL)
            )
        );
        CREATE UNIQUE INDEX native_credentials_one_active_password_uq
            ON request_engine.native_credentials (native_identity_id, kind)
            WHERE status = 'active';
        ALTER TABLE request_engine.native_credentials OWNER TO request_engine_schema_owner;
        REVOKE ALL ON request_engine.native_credentials FROM PUBLIC;

        CREATE TABLE request_engine.native_sessions (
            id uuid PRIMARY KEY,
            native_identity_id uuid NOT NULL REFERENCES request_engine.native_identities(id),
            credential_id uuid NOT NULL REFERENCES request_engine.native_credentials(id),
            token_digest bytea NOT NULL,
            token_fingerprint text NOT NULL,
            session_epoch bigint NOT NULL,
            status text NOT NULL DEFAULT 'active',
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            expires_at timestamptz NOT NULL,
            last_seen_at timestamptz,
            revoked_at timestamptz,
            revocation_reason text,
            CONSTRAINT native_sessions_digest_check CHECK (octet_length(token_digest) = 32),
            CONSTRAINT native_sessions_fingerprint_check CHECK (
                token_fingerprint ~ '^[0-9a-f]{16}$'
            ),
            CONSTRAINT native_sessions_epoch_check CHECK (session_epoch > 0),
            CONSTRAINT native_sessions_status_check CHECK (status IN ('active', 'revoked')),
            CONSTRAINT native_sessions_expiry_check CHECK (expires_at > created_at),
            CONSTRAINT native_sessions_revocation_check CHECK (
                (status = 'revoked' AND revoked_at IS NOT NULL)
                OR (status = 'active' AND revoked_at IS NULL AND revocation_reason IS NULL)
            )
        );
        CREATE UNIQUE INDEX native_sessions_token_digest_uq
            ON request_engine.native_sessions (token_digest);
        CREATE INDEX native_sessions_identity_active_idx
            ON request_engine.native_sessions (native_identity_id, expires_at)
            WHERE status = 'active';
        ALTER TABLE request_engine.native_sessions OWNER TO request_engine_schema_owner;
        REVOKE ALL ON request_engine.native_sessions FROM PUBLIC;

        CREATE TABLE request_engine.native_recovery_intents (
            id uuid PRIMARY KEY,
            native_identity_id uuid NOT NULL REFERENCES request_engine.native_identities(id),
            token_digest bytea NOT NULL,
            token_fingerprint text NOT NULL,
            status text NOT NULL DEFAULT 'pending',
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            expires_at timestamptz NOT NULL,
            consumed_at timestamptz,
            revoked_at timestamptz,
            CONSTRAINT native_recovery_digest_check CHECK (octet_length(token_digest) = 32),
            CONSTRAINT native_recovery_fingerprint_check CHECK (
                token_fingerprint ~ '^[0-9a-f]{16}$'
            ),
            CONSTRAINT native_recovery_status_check CHECK (
                status IN ('pending', 'consumed', 'revoked')
            ),
            CONSTRAINT native_recovery_expiry_check CHECK (expires_at > created_at),
            CONSTRAINT native_recovery_terminal_check CHECK (
                (status = 'pending' AND consumed_at IS NULL AND revoked_at IS NULL)
                OR (status = 'consumed' AND consumed_at IS NOT NULL AND revoked_at IS NULL)
                OR (status = 'revoked' AND consumed_at IS NULL AND revoked_at IS NOT NULL)
            )
        );
        CREATE UNIQUE INDEX native_recovery_token_digest_uq
            ON request_engine.native_recovery_intents (token_digest);
        CREATE INDEX native_recovery_identity_pending_idx
            ON request_engine.native_recovery_intents (native_identity_id, expires_at)
            WHERE status = 'pending';
        ALTER TABLE request_engine.native_recovery_intents OWNER TO request_engine_schema_owner;
        REVOKE ALL ON request_engine.native_recovery_intents FROM PUBLIC;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE request_engine.native_recovery_intents")
    op.execute("DROP TABLE request_engine.native_sessions")
    op.execute("DROP TABLE request_engine.native_credentials")
    op.execute("DROP TABLE request_engine.native_identities")
