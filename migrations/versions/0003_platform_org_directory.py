"""Platform organization directory read surface and owner policy.

Adds a least-privilege platform read projection for organizations and explicitly
extends the immutable Platform Owner policy with that query capability. Existing
owner grants are migrated only when no historical grant for the capability
exists, so a later revocation is never resurrected.

Revision ID: 0003_platform_org_directory
Revises: 0002_discoverable_webauthn_login
Create Date: 2026-09-29
"""

from alembic import op

revision: str = "0003_platform_org_directory"
down_revision: str | None = "0002_discoverable_webauthn_login"
branch_labels: str | None = None
depends_on: str | None = None

_READ_FUNCTION = """
CREATE FUNCTION request_platform.read_platform_organizations(
    p_organization_id uuid,
    p_after uuid,
    p_limit integer
) RETURNS TABLE(
    organization_id uuid,
    organization_key text,
    display_name text,
    operational_status text,
    default_timezone text,
    default_locale text,
    default_currency text,
    created_at timestamp with time zone,
    updated_at timestamp with time zone
)
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
AS $$
BEGIN
    IF p_limit IS NULL OR p_limit < 1 OR p_limit > 100 THEN
        RAISE EXCEPTION 'Organization page limit must be between 1 and 100'
            USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    SELECT organization.id,
           organization.organization_key,
           organization.display_name,
           organization.operational_status,
           organization.default_timezone,
           organization.default_locale,
           organization.default_currency,
           organization.created_at,
           organization.updated_at
      FROM request_engine.organizations AS organization
     WHERE (p_organization_id IS NULL OR organization.id = p_organization_id)
       AND (p_after IS NULL OR organization.id > p_after)
     ORDER BY organization.id
     LIMIT p_limit;
END
$$;

ALTER FUNCTION request_platform.read_platform_organizations(uuid, uuid, integer)
    OWNER TO request_platform_definer;
REVOKE ALL ON FUNCTION request_platform.read_platform_organizations(uuid, uuid, integer)
    FROM PUBLIC;
GRANT SELECT (
    id, organization_key, display_name, operational_status,
    default_timezone, default_locale, default_currency, created_at, updated_at
) ON request_engine.organizations TO request_platform_definer;
"""

_POLICY_AND_GRANTS = """
INSERT INTO request_engine.platform_owner_policies (policy_key, revision, grants)
SELECT 'platform-owner-v4',
       4,
       policy.grants || jsonb_build_array(
           jsonb_build_object(
               'delegable', false,
               'capability_key', 'platform.organization.read'
           )
       )
  FROM request_engine.platform_owner_policies AS policy
 WHERE policy.policy_key = 'platform-owner-v3'
   AND NOT EXISTS (
       SELECT 1
         FROM request_engine.platform_owner_policies
        WHERE policy_key = 'platform-owner-v4'
   );

INSERT INTO request_engine.principal_authority_grants (
    organization_id,
    principal_id,
    principal_plane,
    authority_plane,
    capability_key,
    delegable,
    status,
    granted_by_principal_id,
    provenance_kind,
    provenance_reference
)
SELECT NULL,
       owner_grant.principal_id,
       'platform',
       'platform',
       'platform.organization.read',
       false,
       'active',
       CASE
           WHEN owner_grant.provenance_kind = 'trust_bootstrap' THEN NULL
           ELSE owner_grant.granted_by_principal_id
       END,
       CASE
           WHEN owner_grant.provenance_kind = 'trust_bootstrap' THEN 'trust_bootstrap'
           ELSE 'platform_owner_policy_upgrade'
       END,
       'platform-owner-v4-adoption:' || owner_grant.id::text
  FROM request_engine.principal_authority_grants AS owner_grant
 WHERE owner_grant.principal_plane = 'platform'
   AND owner_grant.authority_plane = 'platform'
   AND owner_grant.capability_key = 'platform.owner.manage_lifecycle'
   AND owner_grant.status = 'active'
   AND NOT EXISTS (
       SELECT 1
         FROM request_engine.principal_authority_grants AS historical
        WHERE historical.principal_id = owner_grant.principal_id
          AND historical.capability_key = 'platform.organization.read'
   );

CREATE FUNCTION request_engine.adopt_platform_owner_v4() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
AS $$
BEGIN
    IF NEW.principal_plane = 'platform'
       AND NEW.authority_plane = 'platform'
       AND NEW.capability_key = 'platform.owner.manage_lifecycle'
       AND NEW.status = 'active'
       AND NOT EXISTS (
           SELECT 1 FROM request_engine.principal_authority_grants AS historical
            WHERE historical.principal_id = NEW.principal_id
              AND historical.capability_key = 'platform.organization.read'
       ) THEN
        INSERT INTO request_engine.principal_authority_grants (
            organization_id, principal_id, principal_plane, authority_plane,
            capability_key, delegable, granted_by_principal_id,
            provenance_kind, provenance_reference
        ) VALUES (
            NULL, NEW.principal_id, 'platform', 'platform',
            'platform.organization.read', false,
            CASE WHEN NEW.provenance_kind = 'trust_bootstrap' THEN NULL
                 ELSE NEW.granted_by_principal_id END,
            CASE WHEN NEW.provenance_kind = 'trust_bootstrap' THEN 'trust_bootstrap'
                 ELSE 'platform_owner_policy_upgrade' END,
            'platform-owner-v4-adoption:' || NEW.id::text
        );
    END IF;
    RETURN NEW;
END
$$;
ALTER FUNCTION request_engine.adopt_platform_owner_v4()
    OWNER TO request_platform_control_definer;
REVOKE ALL ON FUNCTION request_engine.adopt_platform_owner_v4() FROM PUBLIC;
CREATE TRIGGER principal_authority_grants_adopt_platform_owner_v4
AFTER INSERT ON request_engine.principal_authority_grants
FOR EACH ROW EXECUTE FUNCTION request_engine.adopt_platform_owner_v4();
"""


def upgrade() -> None:
    op.execute(_READ_FUNCTION)
    op.execute(_POLICY_AND_GRANTS)


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS principal_authority_grants_adopt_platform_owner_v4 "
        "ON request_engine.principal_authority_grants"
    )
    op.execute("DROP FUNCTION IF EXISTS request_engine.adopt_platform_owner_v4()")
    op.execute(
        "REVOKE SELECT (id, organization_key, display_name, operational_status, "
        "default_timezone, default_locale, default_currency, created_at, updated_at) "
        "ON request_engine.organizations FROM request_platform_definer"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS request_platform.read_platform_organizations(uuid, uuid, integer)"
    )
    # Authority and immutable policy facts are intentionally retained. A downgrade
    # removes executability, but never rewrites security provenance.
