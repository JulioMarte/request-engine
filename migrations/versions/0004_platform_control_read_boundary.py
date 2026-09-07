"""Add a least-privilege read boundary for the platform control plane.

Revision ID: 0004_platform_control_read_boundary
Revises: 0003_principal_authority_grants
Create Date: 2026-09-07
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004_platform_control_read_boundary"
down_revision: str | Sequence[str] | None = "0003_principal_authority_grants"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE ROLE request_engine_platform_control WITH "
        "NOSUPERUSER INHERIT NOCREATEROLE NOCREATEDB NOLOGIN "
        "NOREPLICATION NOBYPASSRLS CONNECTION LIMIT -1"
    )
    op.execute("CREATE SCHEMA request_platform AUTHORIZATION request_engine_schema_owner")
    op.execute("REVOKE ALL ON SCHEMA request_platform FROM PUBLIC")
    op.execute("GRANT USAGE ON SCHEMA request_platform TO request_engine_platform_control")
    op.execute(
        """
        CREATE FUNCTION request_platform.read_principal_authority(p_principal_id uuid)
        RETURNS TABLE (
            principal_kind text,
            active boolean,
            authority_revision bigint,
            capability_key text,
            delegable boolean
        )
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
            SELECT p.principal_kind,
                   p.active,
                   p.authority_revision,
                   g.capability_key,
                   g.delegable
              FROM request_engine.principals AS p
              LEFT JOIN request_engine.principal_authority_grants AS g
                ON g.principal_id = p.id
               AND g.principal_plane = 'platform'
               AND g.authority_plane = 'platform'
               AND g.status = 'active'
             WHERE p.id = p_principal_id
               AND p.principal_plane = 'platform'
             ORDER BY g.capability_key
        $$
        """
    )
    op.execute(
        "ALTER FUNCTION request_platform.read_principal_authority(uuid) "
        "OWNER TO request_engine_schema_owner"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION request_platform.read_principal_authority(uuid) FROM PUBLIC"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION request_platform.read_principal_authority(uuid) "
        "TO request_engine_platform_control"
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION request_platform.read_principal_authority(uuid)")
    op.execute("DROP SCHEMA request_platform")
    op.execute("DROP ROLE request_engine_platform_control")
