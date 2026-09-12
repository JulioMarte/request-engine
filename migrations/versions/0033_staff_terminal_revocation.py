"""Complete invited/suspended staff revocation without relaxing authority checks.

Revision ID: 0033_staff_terminal_revocation
Revises: 0032_native_authority_probe
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0033_staff_terminal_revocation"
down_revision: str | Sequence[str] | None = "0032_native_authority_probe"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FUNCTION = "request_engine.transition_staff_membership(uuid, bigint, text, text)"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION request_engine.transition_staff_membership(
            p_membership_id uuid,
            p_expected_revision bigint,
            p_target_status text,
            p_provenance_reference text
        ) RETURNS bigint
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $$
        DECLARE
            v_actor_id uuid;
            v_org_id uuid := request_engine.current_organization_id();
            v_membership request_engine.staff_memberships%ROWTYPE;
            v_native_identity_id uuid;
        BEGIN
            v_actor_id := request_engine.assert_staff_manager(
                'staff.manage_membership'
            );
            SELECT * INTO v_membership
              FROM request_engine.staff_memberships
             WHERE id = p_membership_id
               AND organization_id = v_org_id
             FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Staff membership not found' USING ERRCODE = 'P0002';
            END IF;
            IF v_membership.principal_id = v_actor_id THEN
                RAISE EXCEPTION 'Staff membership self-transition is forbidden'
                    USING ERRCODE = '42501';
            END IF;
            IF p_expected_revision IS NULL OR p_expected_revision < 1 THEN
                RAISE EXCEPTION 'A positive Staff membership revision is required'
                    USING ERRCODE = '22023';
            END IF;
            IF v_membership.revision <> p_expected_revision THEN
                RAISE EXCEPTION 'Staff membership revision is stale'
                    USING ERRCODE = '40001';
            END IF;
            IF p_provenance_reference IS NULL OR length(btrim(p_provenance_reference)) = 0 THEN
                RAISE EXCEPTION 'Transition provenance is required'
                    USING ERRCODE = '22023';
            END IF;

            IF p_target_status = 'active' THEN
                IF v_membership.status NOT IN ('invited', 'suspended') THEN
                    RAISE EXCEPTION 'Staff membership cannot be activated'
                        USING ERRCODE = '55000';
                END IF;
                UPDATE request_engine.principals
                   SET active = true
                 WHERE id = v_membership.principal_id
                   AND organization_id = v_org_id;
                UPDATE request_engine.identity_bindings
                   SET status = 'active',
                       revision = revision + 1
                 WHERE id = v_membership.identity_binding_id
                   AND organization_id = v_org_id;
                UPDATE request_engine.staff_memberships
                   SET status = 'active',
                       revision = revision + 1,
                       activated_at = COALESCE(activated_at, clock_timestamp()),
                       suspended_at = NULL
                 WHERE id = p_membership_id
                   AND organization_id = v_org_id;
            ELSIF p_target_status IN ('suspended', 'revoked') THEN
                IF (p_target_status = 'suspended' AND v_membership.status <> 'active')
                   OR (p_target_status = 'revoked'
                       AND v_membership.status NOT IN ('invited', 'active', 'suspended')) THEN
                    RAISE EXCEPTION 'Staff membership cannot make this terminal transition'
                        USING ERRCODE = '55000';
                END IF;
                IF (
                    SELECT count(DISTINCT capability_key)
                      FROM request_engine.principal_authority_grants
                     WHERE organization_id = v_org_id
                       AND principal_id = v_membership.principal_id
                       AND status = 'active'
                       AND capability_key IN (
                           'staff.manage_membership',
                           'staff.manage_authority',
                           'identity.bind'
                       )
                ) = 3 THEN
                    PERFORM request_engine.assert_other_tenant_controller(
                        v_membership.principal_id
                    );
                END IF;
                UPDATE request_engine.principals
                   SET active = false
                 WHERE id = v_membership.principal_id
                   AND organization_id = v_org_id;
                UPDATE request_engine.identity_bindings
                   SET status = p_target_status,
                       revision = revision + 1,
                       revoked_at = CASE
                           WHEN p_target_status = 'revoked'
                           THEN clock_timestamp()
                           ELSE NULL
                       END
                 WHERE id = v_membership.identity_binding_id
                   AND organization_id = v_org_id;
                UPDATE request_engine.staff_memberships
                   SET status = p_target_status,
                       revision = revision + 1,
                       suspended_at = CASE
                           WHEN p_target_status = 'suspended'
                           THEN clock_timestamp()
                           ELSE suspended_at
                       END,
                       revoked_at = CASE
                           WHEN p_target_status = 'revoked'
                           THEN clock_timestamp()
                           ELSE NULL
                       END
                 WHERE id = p_membership_id
                   AND organization_id = v_org_id;

                SELECT binding.subject_id::uuid INTO v_native_identity_id
                  FROM request_engine.identity_bindings AS binding
                  JOIN request_engine.identity_authorities AS authority
                    ON authority.id = binding.identity_authority_id
                 WHERE binding.id = v_membership.identity_binding_id
                   AND binding.organization_id = v_org_id
                   AND authority.kind = 'native';
                IF v_native_identity_id IS NOT NULL THEN
                    PERFORM request_auth.revoke_native_sessions(
                        v_native_identity_id,
                        'staff_' || p_target_status
                    );
                END IF;
            ELSE
                RAISE EXCEPTION 'Unsupported Staff membership target status'
                    USING ERRCODE = '22023';
            END IF;
            RETURN p_expected_revision + 1;
        END
        $$;
        """
    )
    op.execute(f"ALTER FUNCTION {_FUNCTION} OWNER TO request_engine_schema_owner")
    op.execute(f"REVOKE ALL ON FUNCTION {_FUNCTION} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {_FUNCTION} TO request_engine_app")


def downgrade() -> None:
    raise RuntimeError("Staff revocation safety requires a forward migration")
