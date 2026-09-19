"""Governed tenant identity-binding lifecycle with an inversion-free lock order.

Block D1b of ``docs/architecture/auth-production-completion-plan.md`` under the
D4/D5 decisions ratified by ADR 0013.

Two coupled changes:

1. The ordered active-staff-membership lock root is now acquired before any
   specific membership or binding row. ``transition_staff_membership`` and
   ``replace_staff_authority`` previously locked a caller-selected membership
   before the ordered root, so two mutually-targeted transitions could each hold
   a specific row and then each request the whole ordered set (``40P01``). The new
   ``lock_tenant_staff_root`` helper takes the root first; every tenant topology
   writer now follows ``gate SHARE -> root -> specific row``.

2. ``request_engine.transition_identity_binding`` exposes the local binding
   lifecycle (``active``/``suspended``/``revoked``) to the tenant control plane
   behind the existing ``identity.bind`` capability. It revalidates the actor, the
   expected revision and tenant controller continuity (D4) inside the same
   transaction. Revoke is terminal; the guard trigger keeps the binding row as an
   append-preserving historical fact.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0046_identity_binding_lifecycle"
down_revision: str | Sequence[str] | None = "0045_identity_recovery_case"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(
        r"""
        CREATE OR REPLACE FUNCTION request_engine.lock_tenant_staff_root()
        RETURNS void
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $$
        BEGIN
            PERFORM id
              FROM request_engine.staff_memberships
             WHERE organization_id = request_engine.current_organization_id()
               AND status = 'active'
             ORDER BY principal_id
             FOR UPDATE;
        END
        $$;
        ALTER FUNCTION request_engine.lock_tenant_staff_root()
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_engine.lock_tenant_staff_root() FROM PUBLIC;

        CREATE OR REPLACE FUNCTION request_engine.assert_tenant_has_controller()
        RETURNS void
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $$
        DECLARE
            v_org_id uuid := request_engine.current_organization_id();
            v_candidate uuid;
        BEGIN
            SELECT membership.principal_id
              INTO v_candidate
              FROM request_engine.staff_memberships AS membership
             WHERE membership.organization_id = v_org_id
               AND membership.status = 'active'
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
        ALTER FUNCTION request_engine.assert_tenant_has_controller()
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_engine.assert_tenant_has_controller() FROM PUBLIC;
        """
    )
    op.execute(
        r"""
CREATE OR REPLACE FUNCTION request_engine.transition_staff_membership(p_membership_id uuid, p_expected_revision bigint, p_target_status text, p_provenance_reference text)
 RETURNS bigint
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
AS $function$
        DECLARE
            v_actor_id uuid;
            v_org_id uuid := request_engine.current_organization_id();
            v_membership request_engine.staff_memberships%ROWTYPE;
            v_native_identity_id uuid;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
            PERFORM request_engine.lock_tenant_staff_root();
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
        $function$;
        """
    )
    op.execute(
        r"""
CREATE OR REPLACE FUNCTION request_engine.replace_staff_authority(p_membership_id uuid, p_expected_authority_revision bigint, p_desired_capabilities text[], p_provenance_reference text)
 RETURNS bigint
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
AS $function$
        DECLARE
            v_actor_id uuid;
            v_target_id uuid;
            v_org_id uuid := request_engine.current_organization_id();
            v_current_revision bigint;
            v_capability text;
            v_plane text;
            v_target_is_controller boolean;
            v_desired_is_controller boolean;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
            PERFORM request_engine.lock_tenant_staff_root();
            v_actor_id := request_engine.assert_staff_manager(
                'staff.manage_authority'
            );
            SELECT membership.principal_id
              INTO v_target_id
              FROM request_engine.staff_memberships AS membership
             WHERE membership.id = p_membership_id
               AND membership.organization_id = v_org_id
               AND membership.status = 'active'
             FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Active Staff membership not found'
                    USING ERRCODE = 'P0002';
            END IF;
            IF v_target_id = v_actor_id THEN
                RAISE EXCEPTION 'Staff authority self-replacement is forbidden'
                    USING ERRCODE = '42501';
            END IF;
            SELECT authority_revision INTO v_current_revision
              FROM request_engine.principals
             WHERE id = v_target_id
             FOR UPDATE;
            IF v_current_revision <> p_expected_authority_revision THEN
                RAISE EXCEPTION 'Staff authority revision is stale'
                    USING ERRCODE = '40001';
            END IF;
            IF length(btrim(p_provenance_reference)) = 0
               OR EXISTS (
                   SELECT 1
                     FROM unnest(COALESCE(p_desired_capabilities, ARRAY[]::text[])) AS cap
                    WHERE length(btrim(cap)) = 0
               )
               OR cardinality(COALESCE(p_desired_capabilities, ARRAY[]::text[])) <>
                  cardinality(
                      ARRAY(
                          SELECT DISTINCT cap
                            FROM unnest(
                                COALESCE(p_desired_capabilities, ARRAY[]::text[])
                            ) AS cap
                      )
                  )
            THEN
                RAISE EXCEPTION 'Desired Staff authority is invalid'
                    USING ERRCODE = '22023';
            END IF;

            FOR v_capability IN
                SELECT cap
                  FROM unnest(
                      COALESCE(p_desired_capabilities, ARRAY[]::text[])
                  ) AS cap
            LOOP
                SELECT authority_plane INTO v_plane
                  FROM request_engine.principal_authority_grants
                 WHERE organization_id = v_org_id
                   AND principal_id = v_actor_id
                   AND capability_key = v_capability
                   AND status = 'active'
                   AND delegable
                 FOR SHARE;
                IF NOT FOUND OR v_plane = 'platform' THEN
                    RAISE EXCEPTION 'Desired authority exceeds delegable ceiling'
                        USING ERRCODE = '42501';
                END IF;
            END LOOP;

            SELECT (
                SELECT count(DISTINCT capability_key) = 3
                  FROM request_engine.principal_authority_grants
                 WHERE principal_id = v_target_id
                   AND status = 'active'
                   AND capability_key IN (
                       'staff.manage_membership',
                       'staff.manage_authority',
                       'identity.bind'
                   )
            ) INTO v_target_is_controller;
            SELECT (
                SELECT count(DISTINCT cap) = 3
                  FROM unnest(
                      COALESCE(p_desired_capabilities, ARRAY[]::text[])
                  ) AS cap
                 WHERE cap IN (
                     'staff.manage_membership',
                     'staff.manage_authority',
                     'identity.bind'
                 )
            ) INTO v_desired_is_controller;
            IF v_target_is_controller AND NOT v_desired_is_controller THEN
                PERFORM request_engine.assert_other_tenant_controller(v_target_id);
            END IF;

            UPDATE request_engine.principal_authority_grants
               SET status = 'revoked',
                   revision = revision + 1,
                   revoked_at = clock_timestamp(),
                   revoked_by_principal_id = v_actor_id
             WHERE organization_id = v_org_id
               AND principal_id = v_target_id
               AND status = 'active'
               AND NOT (
                   capability_key = ANY(
                       COALESCE(p_desired_capabilities, ARRAY[]::text[])
                   )
               );

            FOR v_capability IN
                SELECT cap
                  FROM unnest(
                      COALESCE(p_desired_capabilities, ARRAY[]::text[])
                  ) AS cap
            LOOP
                IF NOT EXISTS (
                    SELECT 1
                      FROM request_engine.principal_authority_grants
                     WHERE principal_id = v_target_id
                       AND capability_key = v_capability
                       AND status = 'active'
                ) THEN
                    SELECT authority_plane INTO v_plane
                      FROM request_engine.principal_authority_grants
                     WHERE principal_id = v_actor_id
                       AND organization_id = v_org_id
                       AND capability_key = v_capability
                       AND status = 'active'
                       AND delegable;
                    INSERT INTO request_engine.principal_authority_grants (
                        organization_id,
                        principal_id,
                        principal_plane,
                        authority_plane,
                        capability_key,
                        delegable,
                        granted_by_principal_id,
                        provenance_kind,
                        provenance_reference
                    ) VALUES (
                        v_org_id,
                        v_target_id,
                        'tenant',
                        v_plane,
                        v_capability,
                        false,
                        v_actor_id,
                        'authority_management',
                        btrim(p_provenance_reference)
                    );
                END IF;
            END LOOP;
            SELECT authority_revision INTO v_current_revision
              FROM request_engine.principals
             WHERE id = v_target_id;
            RETURN v_current_revision;
        END
        $function$;
        """
    )
    op.execute(
        r"""
CREATE OR REPLACE FUNCTION request_engine.transition_identity_binding(p_binding_id uuid, p_expected_revision bigint, p_target_status text, p_provenance_reference text)
 RETURNS bigint
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
AS $function$
        DECLARE
            v_actor_id uuid;
            v_org_id uuid := request_engine.current_organization_id();
            v_binding request_engine.identity_bindings%ROWTYPE;
            v_was_controller boolean;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
            PERFORM request_engine.lock_tenant_staff_root();
            v_actor_id := request_engine.assert_staff_manager('identity.bind');
            SELECT * INTO v_binding
              FROM request_engine.identity_bindings
             WHERE id = p_binding_id
               AND organization_id = v_org_id
               AND principal_plane = 'tenant'
             FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Identity binding not found'
                    USING ERRCODE = 'P0002';
            END IF;
            IF p_expected_revision IS NULL OR p_expected_revision < 1 THEN
                RAISE EXCEPTION 'A positive Identity binding revision is required'
                    USING ERRCODE = '22023';
            END IF;
            IF v_binding.revision <> p_expected_revision THEN
                RAISE EXCEPTION 'Identity binding revision is stale'
                    USING ERRCODE = '40001';
            END IF;
            IF p_provenance_reference IS NULL
               OR length(btrim(p_provenance_reference)) = 0 THEN
                RAISE EXCEPTION 'Transition provenance is required'
                    USING ERRCODE = '22023';
            END IF;
            IF p_target_status = 'suspended' THEN
                IF v_binding.status <> 'active' THEN
                    RAISE EXCEPTION 'Identity binding cannot be suspended'
                        USING ERRCODE = '55000';
                END IF;
            ELSIF p_target_status = 'active' THEN
                IF v_binding.status <> 'suspended' THEN
                    RAISE EXCEPTION 'Identity binding cannot be reactivated'
                        USING ERRCODE = '55000';
                END IF;
            ELSIF p_target_status = 'revoked' THEN
                IF v_binding.status NOT IN ('pending', 'active', 'suspended') THEN
                    RAISE EXCEPTION 'Identity binding cannot be revoked'
                        USING ERRCODE = '55000';
                END IF;
            ELSE
                RAISE EXCEPTION 'Unsupported Identity binding target status'
                    USING ERRCODE = '22023';
            END IF;

            v_was_controller := request_engine.principal_is_effective_tenant_controller(
                v_org_id, v_binding.principal_id
            );

            UPDATE request_engine.identity_bindings
               SET status = p_target_status,
                   revision = revision + 1,
                   revoked_at = CASE
                       WHEN p_target_status = 'revoked'
                       THEN clock_timestamp()
                       ELSE NULL
                   END
             WHERE id = p_binding_id
               AND organization_id = v_org_id;

            IF v_was_controller AND p_target_status IN ('suspended', 'revoked') THEN
                PERFORM request_engine.assert_tenant_has_controller();
            END IF;
            RETURN p_expected_revision + 1;
        END
        $function$;
        ALTER FUNCTION request_engine.transition_identity_binding(
            uuid, bigint, text, text
        ) OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_engine.transition_identity_binding(
            uuid, bigint, text, text
        ) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_engine.transition_identity_binding(
            uuid, bigint, text, text
        ) TO request_engine_app;
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "Do not weaken identity binding lifecycle or the inversion-free lock order; roll forward"
    )
