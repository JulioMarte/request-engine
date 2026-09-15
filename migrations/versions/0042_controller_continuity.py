"""Require an authenticatable path for tenant controller continuity.

An effective tenant controller needs an active Principal, an active membership,
the current control grants and at least one active binding to an active identity
authority. For native subjects the bound identity and its password credential must
be active. Grant-only membership no longer preserves continuity. The authoritative
last-controller check uses this predicate inside the command transaction.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0042_controller_continuity"
down_revision: str | Sequence[str] | None = "0041_native_enrollment_outcome"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("""
        CREATE OR REPLACE FUNCTION request_engine.principal_is_effective_tenant_controller(
            p_organization_id uuid,
            p_principal_id uuid
        ) RETURNS boolean
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $$
        DECLARE
            v_binding record;
            v_authority_kind text;
            v_authority_status text;
        BEGIN
            PERFORM 1
              FROM request_engine.principals AS principal
             WHERE principal.id = p_principal_id
               AND principal.principal_plane = 'tenant'
               AND principal.active;
            IF NOT FOUND THEN
                RETURN false;
            END IF;

            PERFORM 1
              FROM request_engine.staff_memberships AS membership
             WHERE membership.organization_id = p_organization_id
               AND membership.principal_id = p_principal_id
               AND membership.status = 'active';
            IF NOT FOUND THEN
                RETURN false;
            END IF;

            IF (
                SELECT count(DISTINCT grant_row.capability_key)
                  FROM request_engine.principal_authority_grants AS grant_row
                 WHERE grant_row.organization_id = p_organization_id
                   AND grant_row.principal_id = p_principal_id
                   AND grant_row.status = 'active'
                   AND grant_row.capability_key IN (
                       'staff.manage_membership',
                       'staff.manage_authority',
                       'identity.bind'
                   )
            ) <> 3 THEN
                RETURN false;
            END IF;

            FOR v_binding IN
                SELECT binding.identity_authority_id, binding.subject_id
                  FROM request_engine.identity_bindings AS binding
                 WHERE binding.organization_id = p_organization_id
                   AND binding.principal_id = p_principal_id
                   AND binding.principal_plane = 'tenant'
                   AND binding.status = 'active'
                 ORDER BY binding.id
            LOOP
                SELECT authority.kind, authority.status
                  INTO v_authority_kind, v_authority_status
                  FROM request_engine.identity_authorities AS authority
                 WHERE authority.id = v_binding.identity_authority_id;
                IF NOT FOUND OR v_authority_status <> 'active' THEN
                    CONTINUE;
                END IF;

                IF v_authority_kind = 'native' THEN
                    PERFORM 1
                      FROM request_engine.native_identities AS identity
                      JOIN request_engine.native_credentials AS credential
                        ON credential.native_identity_id = identity.id
                       AND credential.kind = 'password'
                       AND credential.status = 'active'
                     WHERE identity.identity_authority_id = v_binding.identity_authority_id
                       AND identity.id::text = v_binding.subject_id
                       AND identity.status = 'active';
                    IF FOUND THEN
                        RETURN true;
                    END IF;
                ELSIF v_authority_kind = 'oidc' THEN
                    -- A configured external authenticator counts; upstream network
                    -- reachability and token revocation are not observable here.
                    RETURN true;
                END IF;
            END LOOP;

            RETURN false;
        END
        $$;
        ALTER FUNCTION request_engine.principal_is_effective_tenant_controller(uuid, uuid)
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_engine.principal_is_effective_tenant_controller(uuid, uuid)
            FROM PUBLIC;

        CREATE OR REPLACE FUNCTION request_engine.assert_other_tenant_controller(
            p_excluded_principal_id uuid
        ) RETURNS void
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $$
        DECLARE
            v_org_id uuid := request_engine.current_organization_id();
            v_candidate uuid;
        BEGIN
            PERFORM id
              FROM request_engine.staff_memberships
             WHERE organization_id = v_org_id
               AND status = 'active'
             ORDER BY principal_id
             FOR UPDATE;

            SELECT membership.principal_id
              INTO v_candidate
              FROM request_engine.staff_memberships AS membership
             WHERE membership.organization_id = v_org_id
               AND membership.status = 'active'
               AND membership.principal_id <> p_excluded_principal_id
               AND request_engine.principal_is_effective_tenant_controller(
                       v_org_id, membership.principal_id)
             ORDER BY membership.principal_id
             LIMIT 1;
            IF v_candidate IS NULL THEN
                RAISE EXCEPTION 'Tenant must retain an active recovery-capable controller'
                    USING ERRCODE = '23514';
            END IF;
        END
        $$;
    """)


def downgrade() -> None:
    raise RuntimeError("Do not weaken tenant controller continuity; roll forward")
