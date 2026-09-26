"""Align offline recovery reset with canonical native-auth lock ordering.

Revision ID: 0070_offline_recovery_lock_order
Revises: 0069_platform_configuration

0068 established the atomic recovery-code password reset. This revision replaces
that function without rewriting applied history so it follows the same
authority -> identity -> recovery-set/code -> credential order as recovery-code
rotation. The code digest is first resolved without a lock, then revalidated
under the authoritative locks before any mutation.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0070_offline_recovery_lock_order"
down_revision: str | Sequence[str] | None = "0069_platform_configuration"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SIGNATURE = "request_auth.consume_recovery_code_and_rotate_password(bytea, uuid, text)"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(f"DROP FUNCTION {_SIGNATURE}")
    op.execute(
        r"""
        CREATE FUNCTION request_auth.consume_recovery_code_and_rotate_password(
            p_code_digest bytea,
            p_new_credential_id uuid,
            p_new_verifier text
        ) RETURNS uuid
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
        DECLARE
            v_code_id uuid;
            v_set_id uuid;
            v_native_identity_id uuid;
            v_authority_id uuid;
            v_identity_status text;
            v_authority_status text;
        BEGIN
            IF p_code_digest IS NULL
               OR octet_length(p_code_digest) <> 32
               OR p_new_credential_id IS NULL
               OR p_new_verifier IS NULL
               OR length(p_new_verifier) <= 32
               OR NOT (
                    p_new_verifier LIKE 'scrypt$%'
                    OR p_new_verifier LIKE '$argon2id$%'
               )
            THEN
                RETURN NULL;
            END IF;

            -- Discovery is deliberately unlocked. Every security-relevant fact
            -- is revalidated later after acquiring canonical locks.
            SELECT code.id, code_set.id, code_set.native_identity_id
              INTO v_code_id, v_set_id, v_native_identity_id
              FROM request_engine.recovery_codes AS code
              JOIN request_engine.recovery_code_sets AS code_set
                ON code_set.id = code.set_id
             WHERE code.code_digest = p_code_digest
               AND code_set.native_identity_id IS NOT NULL;
            IF NOT FOUND THEN
                RETURN NULL;
            END IF;

            SELECT identity.identity_authority_id
              INTO v_authority_id
              FROM request_engine.native_identities AS identity
             WHERE identity.id = v_native_identity_id;
            IF NOT FOUND THEN
                RETURN NULL;
            END IF;

            -- Match create_recovery_code_set: authority first, then identity.
            SELECT authority.status
              INTO v_authority_status
              FROM request_engine.identity_authorities AS authority
             WHERE authority.id = v_authority_id
               AND authority.kind = 'native'
             FOR SHARE;
            IF NOT FOUND OR v_authority_status <> 'active' THEN
                RETURN NULL;
            END IF;

            SELECT identity.status
              INTO v_identity_status
              FROM request_engine.native_identities AS identity
             WHERE identity.id = v_native_identity_id
               AND identity.identity_authority_id = v_authority_id
             FOR UPDATE;
            IF NOT FOUND OR v_identity_status <> 'active' THEN
                RETURN NULL;
            END IF;

            -- Revalidate the bearer proof only after authority/identity locks.
            -- Rotation may have revoked this set while discovery was unlocked.
            SELECT code.id, code_set.id
              INTO v_code_id, v_set_id
              FROM request_engine.recovery_codes AS code
              JOIN request_engine.recovery_code_sets AS code_set
                ON code_set.id = code.set_id
             WHERE code.code_digest = p_code_digest
               AND code.id = v_code_id
               AND code_set.id = v_set_id
               AND code.used_at IS NULL
               AND code_set.status = 'active'
               AND code_set.native_identity_id = v_native_identity_id
             FOR UPDATE OF code, code_set;
            IF NOT FOUND THEN
                RETURN NULL;
            END IF;

            PERFORM 1
              FROM request_engine.native_credentials AS credential
             WHERE credential.native_identity_id = v_native_identity_id
               AND credential.kind = 'password'
               AND credential.status = 'active'
             FOR UPDATE;
            IF NOT FOUND THEN
                RETURN NULL;
            END IF;

            UPDATE request_engine.recovery_codes
               SET used_at = clock_timestamp()
             WHERE id = v_code_id;

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
                   revocation_reason = 'recovery_code_password_reset'
             WHERE native_identity_id = v_native_identity_id
               AND status = 'active';

            UPDATE request_engine.native_recovery_intents
               SET status = 'revoked',
                   revoked_at = clock_timestamp()
             WHERE native_identity_id = v_native_identity_id
               AND status = 'pending';

            INSERT INTO request_engine.platform_recovery_code_facts (
                event_kind, set_id, native_identity_id, code_id,
                actor_principal_id, actor_authentication_method, capability_key,
                correlation_id
            ) VALUES (
                'code_consumed', v_set_id, v_native_identity_id, v_code_id,
                NULLIF(
                    current_setting('request_engine.authenticated_principal_id', true), ''
                )::uuid,
                NULLIF(current_setting('request_engine.authentication_method', true), ''),
                'platform.recovery_codes.password_reset',
                NULLIF(current_setting('request_engine.correlation_id', true), '')::uuid
            );

            RETURN v_native_identity_id;
        END
        $$;
        """
    )
    op.execute(f"ALTER FUNCTION {_SIGNATURE} OWNER TO request_engine_schema_owner")
    op.execute(f"REVOKE ALL ON FUNCTION {_SIGNATURE} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {_SIGNATURE} TO request_engine_app")


def downgrade() -> None:
    raise RuntimeError("Offline recovery mutations are append-preserving; roll forward")
