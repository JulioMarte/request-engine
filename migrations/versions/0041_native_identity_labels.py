"""Add private native account labels without changing the old projection."""

from alembic import op

revision: str = "0041_native_identity_labels"
down_revision: str | None = "0040_tenant_controller_v7"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("""
        GRANT SELECT(login_handle) ON request_engine.native_identities
            TO request_platform_definer;
        CREATE FUNCTION request_platform.read_native_identity_profiles(
            p_identity_id uuid, p_after uuid, p_limit integer
        ) RETURNS TABLE(
            native_identity_id uuid, identity_authority_id uuid, status text,
            revision bigint, created_at timestamptz, disabled_at timestamptz,
            login_handle text
        ) LANGUAGE sql STABLE SECURITY DEFINER
          SET search_path = pg_catalog, request_engine, pg_temp
        AS $$
            SELECT page.native_identity_id, page.identity_authority_id,
                   page.status, page.revision, page.created_at, page.disabled_at,
                   identity.login_handle
              FROM request_platform.read_native_identities(
                  p_identity_id, p_after, p_limit
              ) AS page
              JOIN request_engine.native_identities AS identity
                ON identity.id = page.native_identity_id
             ORDER BY page.native_identity_id
        $$;
        ALTER FUNCTION request_platform.read_native_identity_profiles(uuid,uuid,integer)
            OWNER TO request_platform_definer;
        REVOKE ALL ON FUNCTION
            request_platform.read_native_identity_profiles(uuid,uuid,integer)
            FROM PUBLIC;
    """)


def downgrade() -> None:
    raise RuntimeError("native account label projection is roll-forward only")
