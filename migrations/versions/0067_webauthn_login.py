"""WebAuthn login surface: claim-conflict reader and handle-to-identity lookup.

Revision ID: 0067_webauthn_login
Revises: 0066_claim_hardening

Two narrow additions for the post-claim WebAuthn login block (ADR 0014 §8):

- ``read_installation_claim_intent_digest`` exposes only the stored request
  fingerprint for an idempotency-key digest. It lets the consumed-SetupSession
  replay path distinguish "same key, different fingerprint" (an
  ``idempotency_conflict``) from "key never used / new claim against a closed
  instance" without ever returning another claim's non-secret receipt.
- ``read_active_webauthn_identity`` resolves an active native identity that owns
  at least one active WebAuthn credential from its login handle. It is the only
  handle-to-identity lookup the WebAuthn login ceremony needs; a missing or
  credential-less identity returns NULL so the HTTP layer can answer with an
  indistinguishable decoy instead of an enumeration oracle.

No table or column is added: both functions read existing state.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0067_webauthn_login"
down_revision: str | Sequence[str] | None = "0066_claim_hardening"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEFINER = "request_platform_control_definer"
_RUNTIME = "request_platform_control"
_APP = "request_engine_app"
_SCHEMA_OWNER = "request_engine_schema_owner"

_READ_CLAIM_INTENT_DIGEST = "request_platform.read_installation_claim_intent_digest(text)"
_READ_WEBAUTHN_IDENTITY = "request_auth.read_active_webauthn_identity(uuid, text)"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")

    op.execute(
        r"""
        CREATE FUNCTION request_platform.read_installation_claim_intent_digest(
            p_idempotency_key_digest text
        ) RETURNS text
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $$
            SELECT fact.intent_digest
              FROM request_engine.platform_installation_claim_facts AS fact
             WHERE fact.idempotency_key_digest = p_idempotency_key_digest
        $$;
        """
    )

    op.execute(
        r"""
        CREATE FUNCTION request_auth.read_active_webauthn_identity(
            p_identity_authority_id uuid,
            p_login_handle text
        ) RETURNS uuid
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
            SELECT native_identity.id
              FROM request_engine.native_identities AS native_identity
              JOIN request_engine.identity_authorities AS authority
                ON authority.id = native_identity.identity_authority_id
             WHERE native_identity.identity_authority_id = p_identity_authority_id
               AND native_identity.login_handle = p_login_handle
               AND native_identity.status = 'active'
               AND authority.kind = 'native'
               AND authority.status = 'active'
               AND EXISTS (
                   SELECT 1
                     FROM request_engine.webauthn_credentials AS credential
                    WHERE credential.native_identity_id = native_identity.id
                      AND credential.status = 'active'
               )
        $$;
        """
    )

    op.execute(f"ALTER FUNCTION {_READ_CLAIM_INTENT_DIGEST} OWNER TO {_DEFINER}")
    op.execute(f"REVOKE ALL ON FUNCTION {_READ_CLAIM_INTENT_DIGEST} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {_READ_CLAIM_INTENT_DIGEST} TO {_RUNTIME}")

    op.execute(f"ALTER FUNCTION {_READ_WEBAUTHN_IDENTITY} OWNER TO {_SCHEMA_OWNER}")
    op.execute(f"REVOKE ALL ON FUNCTION {_READ_WEBAUTHN_IDENTITY} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {_READ_WEBAUTHN_IDENTITY} TO {_APP}")


def downgrade() -> None:
    raise RuntimeError("Instance claim state is append-preserving; roll forward")
