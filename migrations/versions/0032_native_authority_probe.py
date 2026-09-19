"""Expose only configured native-authority availability to HTTP readiness.

Revision ID: 0032_native_authority_probe
Revises: 0031_staff_read_authority
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0032_native_authority_probe"
down_revision: str | Sequence[str] | None = "0031_staff_read_authority"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("""
        CREATE FUNCTION request_auth.is_native_authority_ready(p_authority_id uuid)
        RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp' AS $$
            SELECT EXISTS (
                SELECT 1 FROM request_engine.identity_authorities
                 WHERE id = p_authority_id AND kind = 'native' AND status = 'active'
            )
        $$;
        ALTER FUNCTION request_auth.is_native_authority_ready(uuid)
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_auth.is_native_authority_ready(uuid) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_auth.is_native_authority_ready(uuid)
            TO request_engine_app;
    """)


def downgrade() -> None:
    raise RuntimeError("Deploy a forward migration after retiring native authority probes")
