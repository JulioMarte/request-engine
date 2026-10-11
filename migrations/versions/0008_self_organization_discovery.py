"""Subject-bound active staff context discovery before tenant selection.

Read-only, additive projection. Authentication supplies authority/subject; neither
comes from HTTP parameters. Reuses the established authentication read definer,
with only the additional column reads needed for membership usability checks.
No data changes, provider calls or authoritative locks. A discovered context is
advisory and every owner operation still revalidates current tenant authority.
"""

from alembic import op

revision: str = "0008_self_org_discovery"
down_revision: str | None = "0007_controller_read_scope"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("""
        GRANT SELECT (id, kind, status) ON request_engine.identity_authorities
            TO request_platform_definer;
        GRANT SELECT (organization_id) ON request_engine.principals
            TO request_platform_definer;
        GRANT SELECT (id, organization_id, principal_id, status)
            ON request_engine.staff_memberships TO request_platform_definer;
        CREATE FUNCTION request_auth.read_self_organizations(
            p_identity_authority_id uuid, p_subject_id text, p_after uuid, p_limit integer
        ) RETURNS TABLE (
            organization_id uuid, display_name text, principal_id uuid, membership_id uuid
        ) LANGUAGE plpgsql STABLE SECURITY DEFINER
        SET search_path TO pg_catalog, request_engine, pg_temp
        AS $$
        BEGIN
            IF p_limit IS NULL OR p_limit < 1 OR p_limit > 101 THEN
                RAISE EXCEPTION 'Discovery page limit must be between 1 and 101'
                    USING ERRCODE = '22023';
            END IF;
            RETURN QUERY
            SELECT organization.id, organization.display_name, principal.id, membership.id
            FROM request_engine.identity_bindings binding
            JOIN request_engine.identity_authorities authority
              ON authority.id = binding.identity_authority_id AND authority.status = 'active'
            JOIN request_engine.principals principal
              ON principal.id = binding.principal_id
             AND principal.organization_id = binding.organization_id
             AND principal.principal_plane = 'tenant'
             AND principal.principal_kind = 'human' AND principal.active
            JOIN request_engine.staff_memberships membership
              ON membership.organization_id = binding.organization_id
             AND membership.principal_id = principal.id
             AND membership.status = 'active'
            JOIN request_engine.organizations organization
              ON organization.id = binding.organization_id
             AND organization.operational_status = 'active'
            WHERE binding.identity_authority_id = p_identity_authority_id
              AND binding.subject_id = p_subject_id
              AND binding.principal_plane = 'tenant' AND binding.status = 'active'
              AND (p_after IS NULL OR organization.id > p_after)
              AND (authority.kind <> 'native' OR EXISTS (
                  SELECT 1 FROM request_engine.native_identities identity
                  WHERE identity.id::text = binding.subject_id
                    AND identity.identity_authority_id = authority.id AND identity.status = 'active'
              ))
            ORDER BY organization.id LIMIT p_limit;
        END
        $$;
        ALTER FUNCTION request_auth.read_self_organizations(uuid, text, uuid, integer)
            OWNER TO request_platform_definer;
        REVOKE ALL ON FUNCTION request_auth.read_self_organizations(uuid, text, uuid, integer)
            FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_auth.read_self_organizations(uuid, text, uuid, integer)
            TO request_engine_app;
    """)


def downgrade() -> None:
    op.execute("""
        DROP FUNCTION request_auth.read_self_organizations(uuid, text, uuid, integer);
        REVOKE SELECT (id, kind, status) ON request_engine.identity_authorities
            FROM request_platform_definer;
        REVOKE SELECT (organization_id) ON request_engine.principals FROM request_platform_definer;
        REVOKE SELECT (id, organization_id, principal_id, status)
            ON request_engine.staff_memberships FROM request_platform_definer;
    """)
