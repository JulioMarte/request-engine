"""Enforce platform-only provenance for adoption fact approvers.

Adoption facts reference the platform approver by identity. This relation is a
tenant-owned row, so its platform actor reference is the one intentional
cross-plane foreign key and requires a matching structural provenance guard.
"""

from alembic import op

revision: str = "0031_adopt_approver_scope"
down_revision: str | None = "0030_adopt_tenant_fk_scope"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("""
        CREATE OR REPLACE FUNCTION request_engine.guard_authority_reference_tenant()
        RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $$
        DECLARE
            v_actor_ids uuid[];
            v_actor_id uuid;
            v_actor_org uuid;
            v_platform_only boolean := false;
        BEGIN
            CASE TG_TABLE_NAME
                WHEN 'organization_provisioning_facts',
                     'organization_root_provisioning_facts' THEN
                    v_actor_ids := ARRAY[NEW.provisioned_by_principal_id];
                    v_platform_only := true;
                WHEN 'staff_memberships' THEN
                    v_actor_ids := ARRAY[NEW.established_by_principal_id];
                    v_platform_only := NEW.provenance_kind = 'root_provisioning';
                WHEN 'principal_authority_grants' THEN
                    v_actor_ids := ARRAY[
                        NEW.granted_by_principal_id, NEW.revoked_by_principal_id
                    ];
                WHEN 'controller_policy_adoption_facts' THEN
                    v_actor_ids := ARRAY[NEW.platform_approver_principal_id];
                    v_platform_only := true;
                ELSE
                    RAISE EXCEPTION 'Unsupported authority reference relation'
                        USING ERRCODE = '23514';
            END CASE;
            FOREACH v_actor_id IN ARRAY v_actor_ids LOOP
                IF v_actor_id IS NULL THEN CONTINUE; END IF;
                SELECT organization_id INTO v_actor_org
                  FROM request_engine.principals WHERE id = v_actor_id;
                IF NOT FOUND
                   OR (v_platform_only AND v_actor_org IS NOT NULL)
                   OR (NOT v_platform_only AND v_actor_org IS NOT NULL
                       AND v_actor_org IS DISTINCT FROM NEW.organization_id)
                THEN
                    RAISE EXCEPTION 'Authority provenance cannot cross tenant boundaries'
                        USING ERRCODE = '23514';
                END IF;
                IF TG_TABLE_NAME = 'staff_memberships'
                   AND NOT v_platform_only AND v_actor_org IS NULL THEN
                    RAISE EXCEPTION 'Staff invitation requires tenant-local provenance'
                        USING ERRCODE = '23514';
                END IF;
            END LOOP;
            RETURN NEW;
        END
        $$;
        ALTER FUNCTION request_engine.guard_authority_reference_tenant()
            OWNER TO request_platform_control_definer;
        REVOKE ALL ON FUNCTION request_engine.guard_authority_reference_tenant()
            FROM PUBLIC;

        CREATE TRIGGER authority_reference_tenant_guard
            BEFORE INSERT OR UPDATE
            ON request_engine.controller_policy_adoption_facts
            FOR EACH ROW
            EXECUTE FUNCTION request_engine.guard_authority_reference_tenant();
    """)


def downgrade() -> None:
    raise RuntimeError("Adoption approver provenance protection is roll-forward only")
