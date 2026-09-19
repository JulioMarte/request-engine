"""Keep the native-session guard executable by non-schema-owner definers.

Revision ID: 0062_native_session_guard_fix
Revises: 0061_webauthn_trust_fixes

``guard_native_session`` is a plain (non-``SECURITY DEFINER``) trigger that runs as
the current user. It previously called ``request_engine.authentication_assurance_rank``
to compare assurance ranks; when a ``SECURITY DEFINER`` function owned by another
definer (for example ``request_platform.disable_native_identity``) updated a
session, the trigger ran as that definer, which has no EXECUTE on the helper, and
the mutation failed with a spurious permission error. The guard now uses the
built-in ``array_position`` over a literal rank array.

The ``native_sessions`` assurance CHECK has the same problem: PostgreSQL evaluates
CHECK expressions with the invoking user's privileges, so a definer without
EXECUTE on ``derive_authentication_assurance`` could not revoke a session. The
CHECK now derives assurance inline; because every runtime writer derives the same
value through the function, a divergence would make the normal ceremony fail
loudly. The now-unused rank helper is dropped.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0062_native_session_guard_fix"
down_revision: str | Sequence[str] | None = "0061_webauthn_trust_fixes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(
        """
        ALTER TABLE request_engine.native_sessions
            DROP CONSTRAINT native_sessions_assurance_derivation_check;
        ALTER TABLE request_engine.native_sessions
            ADD CONSTRAINT native_sessions_assurance_derivation_check CHECK (
                authentication_assurance = CASE
                    WHEN recovery_derived OR 'recovery_code' = ANY(authentication_methods)
                        THEN 'recovery'
                    WHEN 'webauthn' = ANY(authentication_methods) AND user_verified
                        THEN 'phishing_resistant'
                    WHEN cardinality(authentication_methods)
                         - (CASE WHEN 'recovery_code' = ANY(authentication_methods)
                                 THEN 1 ELSE 0 END) >= 2
                        THEN 'mfa'
                    ELSE 'single_factor'
                END
            );
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
            IF ROW(NEW.id, NEW.native_identity_id, NEW.password_credential_id,
                   NEW.webauthn_credential_id, NEW.token_digest, NEW.token_fingerprint,
                   NEW.session_epoch, NEW.created_at, NEW.expires_at, NEW.recovery_derived)
               IS DISTINCT FROM
               ROW(OLD.id, OLD.native_identity_id, OLD.password_credential_id,
                   OLD.webauthn_credential_id, OLD.token_digest, OLD.token_fingerprint,
                   OLD.session_epoch, OLD.created_at, OLD.expires_at, OLD.recovery_derived)
            THEN
                RAISE EXCEPTION 'Native session credential material is immutable'
                    USING ERRCODE = '55000';
            END IF;
            IF NOT (OLD.authentication_methods <@ NEW.authentication_methods) THEN
                RAISE EXCEPTION 'Native session authentication methods may only grow'
                    USING ERRCODE = '55000';
            END IF;
            IF OLD.user_verified AND NOT NEW.user_verified THEN
                RAISE EXCEPTION 'Native session user verification may not be removed'
                    USING ERRCODE = '55000';
            END IF;
            IF OLD.authentication_assurance <> 'recovery'
               AND NEW.authentication_assurance <> 'recovery'
               AND coalesce(
                       array_position(
                           ARRAY['single_factor', 'mfa', 'phishing_resistant']::text[],
                           NEW.authentication_assurance
                       ), 0)
                   < coalesce(
                       array_position(
                           ARRAY['single_factor', 'mfa', 'phishing_resistant']::text[],
                           OLD.authentication_assurance
                       ), 0)
            THEN
                RAISE EXCEPTION 'Native session assurance may not be downgraded'
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

        DROP FUNCTION IF EXISTS request_engine.authentication_assurance_rank(text);
        """
    )


def downgrade() -> None:
    raise RuntimeError("Native-session guard hardening is append-preserving; roll forward")
