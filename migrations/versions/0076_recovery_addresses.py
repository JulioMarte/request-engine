"""Verified Native HUMAN recovery addresses and generic recovery request.

Revision ID: 0076_recovery_addresses
Revises: 0075_native_recovery_posture

A recovery destination is not trusted merely because an administrator or user
typed it. Native HUMAN identities own explicit recovery addresses that must be
verified by a short-lived one-time proof. Public recovery request lookup remains
inside the request_auth boundary and returns no account-enumeration information.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0076_recovery_addresses"
down_revision: str | Sequence[str] | None = "0075_native_recovery_posture"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(
        r"""
        CREATE TABLE request_engine.native_recovery_addresses (
            id uuid PRIMARY KEY,
            native_identity_id uuid NOT NULL
                REFERENCES request_engine.native_identities(id),
            kind text NOT NULL,
            normalized_address text NOT NULL,
            status text NOT NULL DEFAULT 'pending',
            revision bigint NOT NULL DEFAULT 1,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            verified_at timestamptz,
            revoked_at timestamptz,
            CONSTRAINT native_recovery_addresses_kind_check
                CHECK (kind IN ('email')),
            CONSTRAINT native_recovery_addresses_status_check
                CHECK (status IN ('pending', 'verified', 'revoked')),
            CONSTRAINT native_recovery_addresses_revision_check
                CHECK (revision > 0),
            CONSTRAINT native_recovery_addresses_lifecycle_check CHECK (
                (status = 'pending' AND verified_at IS NULL AND revoked_at IS NULL)
                OR (status = 'verified' AND verified_at IS NOT NULL AND revoked_at IS NULL)
                OR (status = 'revoked' AND revoked_at IS NOT NULL)
            )
        );
        CREATE UNIQUE INDEX native_recovery_addresses_live_uq
            ON request_engine.native_recovery_addresses
            (native_identity_id, kind, normalized_address)
            WHERE status <> 'revoked';
        CREATE INDEX native_recovery_addresses_identity_idx
            ON request_engine.native_recovery_addresses
            (native_identity_id, status, verified_at DESC);
        ALTER TABLE request_engine.native_recovery_addresses
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON request_engine.native_recovery_addresses FROM PUBLIC;

        CREATE TABLE request_engine.native_recovery_address_verifications (
            id uuid PRIMARY KEY,
            recovery_address_id uuid NOT NULL
                REFERENCES request_engine.native_recovery_addresses(id),
            token_digest bytea NOT NULL UNIQUE,
            token_fingerprint text NOT NULL,
            status text NOT NULL DEFAULT 'pending',
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            expires_at timestamptz NOT NULL,
            consumed_at timestamptz,
            revoked_at timestamptz,
            CONSTRAINT native_recovery_address_verifications_digest_check
                CHECK (octet_length(token_digest) = 32),
            CONSTRAINT native_recovery_address_verifications_fingerprint_check
                CHECK (token_fingerprint ~ '^[0-9a-f]{16}$'),
            CONSTRAINT native_recovery_address_verifications_status_check
                CHECK (status IN ('pending', 'consumed', 'revoked')),
            CONSTRAINT native_recovery_address_verifications_time_check
                CHECK (expires_at > created_at),
            CONSTRAINT native_recovery_address_verifications_lifecycle_check CHECK (
                (status = 'pending' AND consumed_at IS NULL AND revoked_at IS NULL)
                OR (status = 'consumed' AND consumed_at IS NOT NULL AND revoked_at IS NULL)
                OR (status = 'revoked' AND revoked_at IS NOT NULL)
            )
        );
        CREATE UNIQUE INDEX native_recovery_address_verifications_pending_uq
            ON request_engine.native_recovery_address_verifications
            (recovery_address_id)
            WHERE status = 'pending';
        ALTER TABLE request_engine.native_recovery_address_verifications
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON request_engine.native_recovery_address_verifications FROM PUBLIC;

        CREATE TABLE request_engine.native_recovery_address_facts (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            native_identity_id uuid NOT NULL,
            recovery_address_id uuid NOT NULL,
            event_kind text NOT NULL,
            correlation_id uuid,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            CONSTRAINT native_recovery_address_facts_kind_check CHECK (
                event_kind IN (
                    'verification_requested',
                    'address_verified',
                    'address_revoked',
                    'recovery_requested'
                )
            )
        );
        ALTER TABLE request_engine.native_recovery_address_facts
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON request_engine.native_recovery_address_facts FROM PUBLIC;
        CREATE TRIGGER native_recovery_address_facts_append_only
            BEFORE DELETE OR UPDATE ON request_engine.native_recovery_address_facts
            FOR EACH ROW EXECUTE FUNCTION request_engine.reject_immutable_mutation();
        """
    )

    op.execute(
        r"""
        CREATE FUNCTION request_auth.prepare_native_recovery_address(
            p_address_id uuid,
            p_native_identity_id uuid,
            p_kind text,
            p_normalized_address text,
            p_verification_id uuid,
            p_token_digest bytea,
            p_token_fingerprint text,
            p_expires_at timestamptz
        )
        RETURNS TABLE (
            recovery_address_id uuid,
            address_status text,
            verification_created boolean
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
        DECLARE
            v_identity_status text;
            v_existing record;
            v_address_id uuid;
        BEGIN
            IF p_address_id IS NULL
               OR p_native_identity_id IS NULL
               OR p_kind <> 'email'
               OR p_normalized_address IS NULL
               OR length(p_normalized_address) NOT BETWEEN 3 AND 320
               OR p_normalized_address !~ '^[^[:space:]@]+@[^[:space:]@]+$'
               OR p_verification_id IS NULL
               OR p_token_digest IS NULL
               OR octet_length(p_token_digest) <> 32
               OR p_token_fingerprint !~ '^[0-9a-f]{16}$'
               OR p_expires_at IS NULL
               OR p_expires_at <= clock_timestamp()
               OR p_expires_at > clock_timestamp() + interval '30 minutes'
            THEN
                RETURN;
            END IF;

            SELECT identity.status
              INTO v_identity_status
              FROM request_engine.native_identities AS identity
             WHERE identity.id = p_native_identity_id
             FOR UPDATE;
            IF NOT FOUND OR v_identity_status <> 'active' THEN
                RETURN;
            END IF;

            SELECT address.id, address.status
              INTO v_existing
              FROM request_engine.native_recovery_addresses AS address
             WHERE address.native_identity_id = p_native_identity_id
               AND address.kind = p_kind
               AND address.normalized_address = p_normalized_address
               AND address.status <> 'revoked'
             FOR UPDATE;

            IF FOUND AND v_existing.status = 'verified' THEN
                RETURN QUERY SELECT v_existing.id, 'verified'::text, false;
                RETURN;
            END IF;

            IF FOUND THEN
                v_address_id := v_existing.id;
                UPDATE request_engine.native_recovery_address_verifications
                   SET status = 'revoked',
                       revoked_at = clock_timestamp()
                 WHERE recovery_address_id = v_address_id
                   AND status = 'pending';
            ELSE
                v_address_id := p_address_id;
                INSERT INTO request_engine.native_recovery_addresses (
                    id, native_identity_id, kind, normalized_address
                ) VALUES (
                    v_address_id,
                    p_native_identity_id,
                    p_kind,
                    p_normalized_address
                );
            END IF;

            INSERT INTO request_engine.native_recovery_address_verifications (
                id,
                recovery_address_id,
                token_digest,
                token_fingerprint,
                expires_at
            ) VALUES (
                p_verification_id,
                v_address_id,
                p_token_digest,
                p_token_fingerprint,
                p_expires_at
            );

            INSERT INTO request_engine.native_recovery_address_facts (
                native_identity_id,
                recovery_address_id,
                event_kind,
                correlation_id
            ) VALUES (
                p_native_identity_id,
                v_address_id,
                'verification_requested',
                NULLIF(current_setting('request_engine.correlation_id', true), '')::uuid
            );

            RETURN QUERY SELECT v_address_id, 'pending'::text, true;
        END
        $$;

        CREATE FUNCTION request_auth.verify_native_recovery_address(
            p_verification_id uuid,
            p_token_digest bytea
        ) RETURNS uuid
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
        DECLARE
            v_address_id uuid;
            v_identity_id uuid;
            v_address_status text;
        BEGIN
            IF p_verification_id IS NULL
               OR p_token_digest IS NULL
               OR octet_length(p_token_digest) <> 32
            THEN
                RETURN NULL;
            END IF;

            SELECT verification.recovery_address_id
              INTO v_address_id
              FROM request_engine.native_recovery_address_verifications AS verification
             WHERE verification.id = p_verification_id
               AND verification.token_digest = p_token_digest
               AND verification.status = 'pending'
               AND verification.expires_at > clock_timestamp()
             FOR UPDATE;
            IF NOT FOUND THEN
                RETURN NULL;
            END IF;

            SELECT address.native_identity_id, address.status
              INTO v_identity_id, v_address_status
              FROM request_engine.native_recovery_addresses AS address
             WHERE address.id = v_address_id
             FOR UPDATE;
            IF NOT FOUND OR v_address_status <> 'pending' THEN
                RETURN NULL;
            END IF;

            UPDATE request_engine.native_recovery_address_verifications
               SET status = 'consumed',
                   consumed_at = clock_timestamp()
             WHERE id = p_verification_id;

            UPDATE request_engine.native_recovery_addresses
               SET status = 'verified',
                   revision = revision + 1,
                   verified_at = clock_timestamp()
             WHERE id = v_address_id;

            INSERT INTO request_engine.native_recovery_address_facts (
                native_identity_id,
                recovery_address_id,
                event_kind,
                correlation_id
            ) VALUES (
                v_identity_id,
                v_address_id,
                'address_verified',
                NULLIF(current_setting('request_engine.correlation_id', true), '')::uuid
            );
            RETURN v_identity_id;
        END
        $$;

        CREATE FUNCTION request_auth.read_native_recovery_addresses(
            p_native_identity_id uuid
        )
        RETURNS TABLE (
            recovery_address_id uuid,
            kind text,
            normalized_address text,
            status text,
            revision bigint,
            verified_at timestamptz,
            created_at timestamptz
        )
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
            SELECT address.id,
                   address.kind,
                   address.normalized_address,
                   address.status,
                   address.revision,
                   address.verified_at,
                   address.created_at
              FROM request_engine.native_recovery_addresses AS address
             WHERE address.native_identity_id = p_native_identity_id
               AND address.status <> 'revoked'
             ORDER BY address.created_at, address.id
        $$;

        CREATE FUNCTION request_auth.revoke_native_recovery_address(
            p_native_identity_id uuid,
            p_recovery_address_id uuid
        ) RETURNS boolean
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
        DECLARE
            v_address_status text;
        BEGIN
            SELECT address.status
              INTO v_address_status
              FROM request_engine.native_recovery_addresses AS address
             WHERE address.id = p_recovery_address_id
               AND address.native_identity_id = p_native_identity_id
             FOR UPDATE;
            IF NOT FOUND OR v_address_status = 'revoked' THEN
                RETURN false;
            END IF;

            UPDATE request_engine.native_recovery_address_verifications
               SET status = 'revoked',
                   revoked_at = clock_timestamp()
             WHERE recovery_address_id = p_recovery_address_id
               AND status = 'pending';

            UPDATE request_engine.native_recovery_addresses
               SET status = 'revoked',
                   revision = revision + 1,
                   revoked_at = clock_timestamp()
             WHERE id = p_recovery_address_id;

            INSERT INTO request_engine.native_recovery_address_facts (
                native_identity_id,
                recovery_address_id,
                event_kind,
                correlation_id
            ) VALUES (
                p_native_identity_id,
                p_recovery_address_id,
                'address_revoked',
                NULLIF(current_setting('request_engine.correlation_id', true), '')::uuid
            );
            RETURN true;
        END
        $$;

        CREATE FUNCTION request_auth.create_native_recovery_intent_for_verified_address(
            p_identity_authority_id uuid,
            p_login_handle text,
            p_recovery_id uuid,
            p_token_digest bytea,
            p_token_fingerprint text,
            p_expires_at timestamptz
        )
        RETURNS TABLE (
            native_identity_id uuid,
            recovery_address_id uuid,
            destination_address text
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
        DECLARE
            v_identity_id uuid;
            v_address record;
        BEGIN
            IF p_identity_authority_id IS NULL
               OR p_login_handle IS NULL
               OR p_recovery_id IS NULL
               OR p_token_digest IS NULL
               OR octet_length(p_token_digest) <> 32
               OR p_token_fingerprint !~ '^[0-9a-f]{16}$'
               OR p_expires_at IS NULL
               OR p_expires_at <= clock_timestamp()
               OR p_expires_at > clock_timestamp() + interval '30 minutes'
            THEN
                RETURN;
            END IF;

            PERFORM 1
              FROM request_engine.identity_authorities AS authority
             WHERE authority.id = p_identity_authority_id
               AND authority.kind = 'native'
               AND authority.status = 'active'
             FOR SHARE;
            IF NOT FOUND THEN
                RETURN;
            END IF;

            SELECT identity.id
              INTO v_identity_id
              FROM request_engine.native_identities AS identity
             WHERE identity.identity_authority_id = p_identity_authority_id
               AND identity.login_handle = p_login_handle
               AND identity.status = 'active'
             FOR UPDATE;
            IF NOT FOUND THEN
                RETURN;
            END IF;

            SELECT address.id, address.normalized_address
              INTO v_address
              FROM request_engine.native_recovery_addresses AS address
             WHERE address.native_identity_id = v_identity_id
               AND address.kind = 'email'
               AND address.status = 'verified'
             ORDER BY address.verified_at DESC, address.id
             LIMIT 1
             FOR SHARE;
            IF NOT FOUND THEN
                RETURN;
            END IF;

            UPDATE request_engine.native_recovery_intents
               SET status = 'revoked',
                   revoked_at = clock_timestamp()
             WHERE native_identity_id = v_identity_id
               AND status = 'pending';

            INSERT INTO request_engine.native_recovery_intents (
                id,
                native_identity_id,
                token_digest,
                token_fingerprint,
                expires_at
            ) VALUES (
                p_recovery_id,
                v_identity_id,
                p_token_digest,
                p_token_fingerprint,
                p_expires_at
            );

            INSERT INTO request_engine.native_recovery_address_facts (
                native_identity_id,
                recovery_address_id,
                event_kind,
                correlation_id
            ) VALUES (
                v_identity_id,
                v_address.id,
                'recovery_requested',
                NULLIF(current_setting('request_engine.correlation_id', true), '')::uuid
            );

            RETURN QUERY SELECT
                v_identity_id,
                v_address.id,
                v_address.normalized_address;
        END
        $$;
        """
    )

    signatures = (
        "prepare_native_recovery_address(uuid, uuid, text, text, uuid, bytea, text, timestamptz)",
        "verify_native_recovery_address(uuid, bytea)",
        "read_native_recovery_addresses(uuid)",
        "revoke_native_recovery_address(uuid, uuid)",
        (
            "create_native_recovery_intent_for_verified_address("
            "uuid, text, uuid, bytea, text, timestamptz)"
        ),
    )
    for signature in signatures:
        op.execute(f"ALTER FUNCTION request_auth.{signature} OWNER TO request_engine_schema_owner")
        op.execute(f"REVOKE ALL ON FUNCTION request_auth.{signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION request_auth.{signature} TO request_engine_app")


def downgrade() -> None:
    raise RuntimeError("Verified recovery-address history is append-preserving; roll forward")
