"""Restrict staff controller inspection to the authenticated tenant planner.

Revision ID: 0007_controller_read_scope
Revises: 0006_staff_controller_continuity

Tenancy-owned read-only privilege correction. No data backfill or write locks.
The internal cross-tenant predicate remains available to owner commands only;
the application projection derives its tenant and actor from trusted context.
Deploy with the updated reader: older readers fail closed after this revision.
Downgrade restores the previous, overly broad application grant.
"""

from alembic import op

revision: str = "0007_controller_read_scope"
down_revision: str | None = "0006_staff_controller_continuity"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("""
        CREATE FUNCTION request_read.staff_controller_is_effective(p_principal_id uuid)
        RETURNS boolean
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path TO pg_catalog, request_engine, pg_temp
        AS $$
            SELECT CASE WHEN EXISTS (
                SELECT 1 FROM request_engine.principals actor
                JOIN request_engine.staff_memberships membership
                  ON membership.organization_id = actor.organization_id
                 AND membership.principal_id = actor.id
                 AND membership.status = 'active'
                JOIN request_engine.principal_authority_grants grant_row
                  ON grant_row.organization_id = actor.organization_id
                 AND grant_row.principal_id = actor.id
                 AND grant_row.capability_key IN (
                     'staff.plan_authority', 'staff.manage_authority'
                 )
                 AND grant_row.authority_plane = 'tenant_control'
                 AND grant_row.status = 'active'
                WHERE actor.organization_id = request_engine.current_organization_id()
                  AND actor.id = request_engine.current_authenticated_principal_id()
                  AND actor.active AND actor.principal_kind = 'human'
            ) THEN request_engine.principal_is_effective_tenant_controller(
                request_engine.current_organization_id(), p_principal_id
            ) ELSE false END
        $$;
        ALTER FUNCTION request_read.staff_controller_is_effective(uuid)
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_read.staff_controller_is_effective(uuid) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_read.staff_controller_is_effective(uuid)
            TO request_engine_app;
        REVOKE EXECUTE ON FUNCTION
            request_engine.principal_is_effective_tenant_controller(uuid, uuid)
            FROM request_engine_app;
    """)


def downgrade() -> None:
    op.execute("""
        DROP FUNCTION request_read.staff_controller_is_effective(uuid);
        GRANT EXECUTE ON FUNCTION
            request_engine.principal_is_effective_tenant_controller(uuid, uuid)
            TO request_engine_app;
    """)
