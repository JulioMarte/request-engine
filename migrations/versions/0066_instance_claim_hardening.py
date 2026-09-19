"""Instance claim hardening: request-fingerprint idempotency and session-bound WebAuthn completion.

Revision ID: 0066_claim_hardening
Revises: 0065_instance_claim

Two closed gaps in the P4 Instance claim surface (ADR 0014 §6, §8, §9):

- ``read_installation_claim`` now filters by the request fingerprint
  (``intent_digest``) as well as the idempotency-key digest. Previously the
  consumed-SetupSession replay path looked a claim fact up by key alone, so the
  same key reused with different request content returned a foreign receipt.
  Exact replay requires the same key *and* the same fingerprint;
  key-reuse-with-different-request is a conflict.
- ``finalize_setup_webauthn_registration`` now requires the presented
  SetupSession to be the one that owns the consumed challenge. A valid bearer
  for another concurrent ceremony can no longer complete this registration.

``finalize_instance_claim`` itself is unchanged: it already compares the stored
``intent_digest`` against the caller's value, so the Python-owned fingerprint
takes effect without a signature change.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0066_claim_hardening"
down_revision: str | Sequence[str] | None = "0065_instance_claim"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEFINER = "request_platform_control_definer"
_RUNTIME = "request_platform_control"
_APP = "request_engine_app"
_SCHEMA_OWNER = "request_engine_schema_owner"

_OLD_READ_INSTALLATION_CLAIM = "request_platform.read_installation_claim(text)"
_NEW_READ_INSTALLATION_CLAIM = "request_platform.read_installation_claim(text, text)"
_OLD_FINALIZE_SETUP = (
    "request_auth.finalize_setup_webauthn_registration("
    "bytea, uuid, bytea, bytea, bigint, text, boolean, boolean, boolean)"
)
_NEW_FINALIZE_SETUP = (
    "request_auth.finalize_setup_webauthn_registration("
    "bytea, uuid, bytea, bytea, bigint, text, boolean, boolean, boolean, uuid)"
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")

    op.execute(f"DROP FUNCTION {_OLD_READ_INSTALLATION_CLAIM}")
    op.execute(f"DROP FUNCTION {_OLD_FINALIZE_SETUP}")

    op.execute(
        r"""
        CREATE FUNCTION request_platform.read_installation_claim(
            p_idempotency_key_digest text,
            p_intent_digest text
        )
        RETURNS TABLE (
            instance_id uuid,
            owner_principal_id uuid,
            native_identity_id uuid,
            setup_session_id uuid,
            policy_key text,
            claim_provenance text,
            intent_digest text,
            claimed_at timestamptz
        )
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $$
            SELECT fact.instance_id,
                   fact.owner_principal_id,
                   fact.native_identity_id,
                   fact.setup_session_id,
                   fact.policy_key,
                   fact.claim_provenance,
                   fact.intent_digest,
                   fact.created_at
              FROM request_engine.platform_installation_claim_facts AS fact
             WHERE fact.idempotency_key_digest = p_idempotency_key_digest
               AND fact.intent_digest = p_intent_digest
        $$;
        """
    )

    op.execute(
        r"""
        CREATE FUNCTION request_auth.finalize_setup_webauthn_registration(
            p_challenge_digest bytea,
            p_credential_row_id uuid,
            p_credential_id_bytes bytea,
            p_public_key bytea,
            p_sign_count bigint,
            p_aaguid text,
            p_backup_eligible boolean,
            p_backup_state boolean,
            p_user_verified boolean,
            p_setup_session_id uuid
        ) RETURNS boolean
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
        DECLARE
            v_challenge request_engine.webauthn_challenges%ROWTYPE;
            v_setup_status text;
            v_instance_state text;
            v_expires_at timestamptz;
        BEGIN
            IF p_challenge_digest IS NULL
               OR octet_length(p_challenge_digest) <> 32
               OR p_credential_row_id IS NULL
               OR p_credential_id_bytes IS NULL
               OR octet_length(p_credential_id_bytes) NOT BETWEEN 16 AND 1023
               OR p_public_key IS NULL
               OR octet_length(p_public_key) = 0
               OR p_sign_count < 0
               OR p_aaguid IS NULL
               OR p_aaguid !~ '^[0-9a-f]{32}$'
               OR p_setup_session_id IS NULL
            THEN
                RETURN false;
            END IF;

            SELECT challenge.* INTO v_challenge
              FROM request_engine.webauthn_challenges AS challenge
             WHERE challenge.challenge_digest = p_challenge_digest
               AND challenge.purpose = 'registration'
               AND challenge.status = 'pending'
               AND challenge.expires_at > clock_timestamp()
             FOR UPDATE;
            -- The presented SetupSession must own the challenge. A valid bearer
            -- for a different concurrent ceremony is never sufficient.
            IF NOT FOUND
               OR v_challenge.setup_session_id IS NULL
               OR v_challenge.setup_session_id <> p_setup_session_id
            THEN
                RETURN false;
            END IF;

            SELECT session.status, session.expires_at, instance.state
              INTO v_setup_status, v_expires_at, v_instance_state
              FROM request_engine.setup_sessions AS session
              JOIN request_engine.platform_instance AS instance
                ON instance.id = session.instance_id
             WHERE session.id = v_challenge.setup_session_id
             FOR UPDATE OF session;
            IF NOT FOUND
               OR v_setup_status <> 'pending'
               OR v_expires_at <= clock_timestamp()
               OR v_instance_state <> 'unclaimed'
            THEN
                RETURN false;
            END IF;

            INSERT INTO request_engine.setup_pending_webauthn_credential (
                id, setup_session_id, credential_id, public_key, sign_count,
                aaguid, backup_eligible, backup_state, user_verified
            ) VALUES (
                p_credential_row_id, v_challenge.setup_session_id, p_credential_id_bytes,
                p_public_key, p_sign_count, p_aaguid, p_backup_eligible,
                p_backup_state, p_user_verified
            )
            ON CONFLICT (credential_id) DO NOTHING;
            IF NOT FOUND THEN
                RETURN false;
            END IF;

            UPDATE request_engine.webauthn_challenges
               SET status = 'consumed', consumed_at = clock_timestamp()
             WHERE id = v_challenge.id;
            RETURN true;
        END
        $$;
        """
    )

    op.execute(f"ALTER FUNCTION {_NEW_READ_INSTALLATION_CLAIM} OWNER TO {_DEFINER}")
    op.execute(f"REVOKE ALL ON FUNCTION {_NEW_READ_INSTALLATION_CLAIM} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {_NEW_READ_INSTALLATION_CLAIM} TO {_RUNTIME}")

    op.execute(f"ALTER FUNCTION {_NEW_FINALIZE_SETUP} OWNER TO {_SCHEMA_OWNER}")
    op.execute(f"REVOKE ALL ON FUNCTION {_NEW_FINALIZE_SETUP} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {_NEW_FINALIZE_SETUP} TO {_APP}")


def downgrade() -> None:
    raise RuntimeError("Instance claim state is append-preserving; roll forward")
