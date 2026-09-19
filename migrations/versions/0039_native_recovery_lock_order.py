"""Serialize recovery intents on their identity before locking individual intents."""

from collections.abc import Sequence

from alembic import op

revision: str = "0039_native_recovery_lock_order"
down_revision: str | Sequence[str] | None = "0038_self_authority_policy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    # CREATE OR REPLACE preserves the existing owner and EXECUTE grants.
    op.execute("""
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
            -- the shared serialization root for rotation, disable and recovery.
            SELECT r.native_identity_id INTO v_native_identity_id
              FROM request_engine.native_recovery_intents r
             WHERE r.id = p_recovery_id AND r.token_digest = p_token_digest
               AND r.status = 'pending' AND r.expires_at > clock_timestamp();
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
    raise RuntimeError("Do not restore the native recovery lock inversion; roll forward")
