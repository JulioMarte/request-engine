"""Distinguish duplicate Native enrollment from an unavailable identity authority.

`request_auth.create_native_identity` keeps its signature, owner, SECURITY DEFINER
boundary, pinned search_path and EXECUTE ACL: true=created, false=duplicate login
handle, NULL=authority absent, disabled or of another kind. The authority SHARE
lock from 0040 is preserved and rejection happens before identity/credential writes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0041_native_enrollment_outcome"
down_revision: str | Sequence[str] | None = "0040_native_authority_gate"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("""
        CREATE OR REPLACE FUNCTION request_auth.create_native_identity(
            p_identity_authority_id uuid,
            p_native_identity_id uuid,
            p_login_handle text,
            p_credential_id uuid,
            p_verifier text
        ) RETURNS boolean
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
        DECLARE
            v_identity_id uuid;
        BEGIN
            PERFORM 1
              FROM request_engine.identity_authorities
             WHERE id = p_identity_authority_id
               AND status = 'active' AND kind = 'native'
             FOR SHARE;
            IF NOT FOUND THEN
                RETURN NULL;
            END IF;

            INSERT INTO request_engine.native_identities (
                id, identity_authority_id, login_handle
            ) VALUES (
                p_native_identity_id, p_identity_authority_id, p_login_handle
            )
            ON CONFLICT (identity_authority_id, login_handle) DO NOTHING
            RETURNING id INTO v_identity_id;
            IF v_identity_id IS NULL THEN
                RETURN false;
            END IF;

            INSERT INTO request_engine.native_credentials (
                id, native_identity_id, verifier
            ) VALUES (
                p_credential_id, p_native_identity_id, p_verifier
            );
            RETURN true;
        END
        $$;
    """)


def downgrade() -> None:
    raise RuntimeError("Do not collapse Native enrollment outcomes; roll forward")
