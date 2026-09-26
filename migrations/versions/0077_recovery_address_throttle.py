"""Throttle verified-address recovery requests without account enumeration.

Revision ID: 0077_recovery_addr_throttle
Revises: 0076_recovery_addresses

A public recovery request must not become an email-spam primitive. The
per-identity/address database boundary suppresses another dispatch for one
minute while preserving the same empty result used for unknown identities and
missing verified destinations. Edge/IP throttling remains a deployment concern.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0077_recovery_addr_throttle"
down_revision: str | Sequence[str] | None = "0076_recovery_addresses"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(
        r"""
        CREATE OR REPLACE FUNCTION request_auth.create_native_recovery_intent_for_verified_address(
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

            -- Durable per-account throttling. Returning no row is deliberate:
            -- callers receive the same public response as an unknown account.
            PERFORM 1
              FROM request_engine.native_recovery_address_facts AS fact
             WHERE fact.native_identity_id = v_identity_id
               AND fact.recovery_address_id = v_address.id
               AND fact.event_kind = 'recovery_requested'
               AND fact.created_at > clock_timestamp() - interval '1 minute'
             LIMIT 1;
            IF FOUND THEN
                RETURN;
            END IF;

            UPDATE request_engine.native_recovery_intents AS intent
               SET status = 'revoked',
                   revoked_at = clock_timestamp()
             WHERE intent.native_identity_id = v_identity_id
               AND intent.status = 'pending';

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

        ALTER FUNCTION request_auth.create_native_recovery_intent_for_verified_address(
            uuid, text, uuid, bytea, text, timestamptz
        ) OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_auth.create_native_recovery_intent_for_verified_address(
            uuid, text, uuid, bytea, text, timestamptz
        ) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_auth.create_native_recovery_intent_for_verified_address(
            uuid, text, uuid, bytea, text, timestamptz
        ) TO request_engine_app;
        """
    )


def downgrade() -> None:
    raise RuntimeError("Recovery-address request throttling is roll-forward only")
