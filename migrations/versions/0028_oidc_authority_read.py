"""Add the runtime read boundary for active OIDC identity authorities.

Revision ID: 0028_oidc_authority_read
Revises: 0027_integration_governance
Create Date: 2026-09-09

OIDC authentication is optional at composition: with no OIDC authorities
configured the deployment behaves exactly as before. The runtime app role has
no direct SELECT on request_engine.identity_authorities; authentication reads
of protected authority rows go through one SECURITY DEFINER function that
returns only active ``oidc`` rows.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0028_oidc_authority_read"
down_revision: str | Sequence[str] | None = "0027_integration_governance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION request_auth.read_oidc_authorities()
        RETURNS TABLE (
            id uuid,
            issuer_or_environment text,
            configuration_ref text
        )
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $$
            SELECT id,
                   issuer_or_environment,
                   configuration_ref
              FROM request_engine.identity_authorities
             WHERE kind = 'oidc'
               AND status = 'active'
        $$;
        ALTER FUNCTION request_auth.read_oidc_authorities()
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_auth.read_oidc_authorities() FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_auth.read_oidc_authorities()
            TO request_engine_app;
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION request_auth.read_oidc_authorities()")
