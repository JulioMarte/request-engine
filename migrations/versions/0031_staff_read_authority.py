"""Materialize explicit staff inspection authority for native tenant roots.

Revision ID: 0031_staff_read_authority
Revises: 0030_integration_provenance
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0031_staff_read_authority"
down_revision: str | Sequence[str] | None = "0030_integration_provenance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("""
        CREATE FUNCTION request_engine.seed_root_staff_read_authority()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp' AS $$
        BEGIN
            PERFORM set_config('request_engine.organization_id', NEW.organization_id::text, true);
            INSERT INTO request_engine.principal_authority_grants (
                organization_id, principal_id, principal_plane, authority_plane,
                capability_key, delegable, granted_by_principal_id,
                provenance_kind, provenance_reference
            ) VALUES (
                NEW.organization_id, NEW.controller_principal_id, 'tenant', 'tenant_control',
                'staff.read', true, NEW.provisioned_by_principal_id,
                'provisioning', concat(NEW.provenance_reference, '-staff-inspection-v1')
            );
            RETURN NEW;
        END $$;
        ALTER FUNCTION request_engine.seed_root_staff_read_authority()
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_engine.seed_root_staff_read_authority() FROM PUBLIC;
        CREATE TRIGGER organization_root_seed_staff_read_authority
            AFTER INSERT ON request_engine.organization_root_provisioning_facts
            FOR EACH ROW EXECUTE FUNCTION request_engine.seed_root_staff_read_authority();
    """)
    # Add only the missing read facet to still-active original controllers.
    # Any historical grant (including revoked) prevents reinstatement.
    op.execute("""
        INSERT INTO request_engine.principal_authority_grants (
            organization_id, principal_id, principal_plane, authority_plane,
            capability_key, delegable, granted_by_principal_id,
            provenance_kind, provenance_reference
        )
        SELECT f.organization_id, f.controller_principal_id, 'tenant', 'tenant_control',
               'staff.read', true, f.provisioned_by_principal_id, 'provisioning',
               concat(f.provenance_reference, '-staff-inspection-v1')
          FROM request_engine.organization_root_provisioning_facts f
          JOIN request_engine.principals p ON p.id = f.controller_principal_id
         WHERE p.active AND EXISTS (
             SELECT 1 FROM request_engine.staff_memberships m
              WHERE m.organization_id = f.organization_id AND m.principal_id = p.id
                AND m.status = 'active'
         ) AND 3 = (
             SELECT count(DISTINCT g.capability_key)
               FROM request_engine.principal_authority_grants g
              WHERE g.organization_id = f.organization_id AND g.principal_id = p.id
                AND g.status = 'active' AND g.authority_plane = 'tenant_control'
                AND g.capability_key IN (
                    'staff.manage_authority', 'staff.manage_membership', 'identity.bind'
                )
         ) AND NOT EXISTS (
             SELECT 1 FROM request_engine.principal_authority_grants g
              WHERE g.principal_id = p.id AND g.capability_key = 'staff.read'
         );
    """)


def downgrade() -> None:
    raise RuntimeError("Staff read grants preserve authority provenance; use a forward migration")
