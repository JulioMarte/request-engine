"""Expose Native session verification through a narrow read boundary.

Revision ID: 0008_native_auth_read
Revises: 0007_native_human_auth
Create Date: 2026-09-08
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008_native_auth_read"
down_revision: str | Sequence[str] | None = "0007_native_human_auth"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA request_auth AUTHORIZATION request_engine_schema_owner")
    op.execute("REVOKE ALL ON SCHEMA request_auth FROM PUBLIC")
    op.execute("GRANT USAGE ON SCHEMA request_auth TO request_engine_app")
    op.execute(
        """
        CREATE FUNCTION request_auth.read_native_session(p_session_id uuid)
        RETURNS TABLE (
            session_id uuid,
            native_identity_id uuid,
            identity_authority_id uuid,
            credential_id uuid,
            token_digest bytea,
            session_epoch bigint,
            current_session_epoch bigint,
            session_status text,
            identity_status text,
            credential_status text,
            expires_at timestamptz
        )
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
            SELECT s.id,
                   s.native_identity_id,
                   i.identity_authority_id,
                   s.credential_id,
                   s.token_digest,
                   s.session_epoch,
                   i.session_epoch,
                   s.status,
                   i.status,
                   c.status,
                   s.expires_at
              FROM request_engine.native_sessions AS s
              JOIN request_engine.native_identities AS i
                ON i.id = s.native_identity_id
              JOIN request_engine.native_credentials AS c
                ON c.id = s.credential_id
               AND c.native_identity_id = s.native_identity_id
             WHERE s.id = p_session_id
        $$
        """
    )
    op.execute(
        "ALTER FUNCTION request_auth.read_native_session(uuid) OWNER TO request_engine_schema_owner"
    )
    op.execute("REVOKE ALL ON FUNCTION request_auth.read_native_session(uuid) FROM PUBLIC")
    op.execute(
        "GRANT EXECUTE ON FUNCTION request_auth.read_native_session(uuid) TO request_engine_app"
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION request_auth.read_native_session(uuid)")
    op.execute("REVOKE USAGE ON SCHEMA request_auth FROM request_engine_app")
    op.execute("DROP SCHEMA request_auth")
