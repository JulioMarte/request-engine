"""Report readiness against the latest applied controller policy adoption."""

from alembic import op

revision: str = "0029_ctrl_adopt_readiness"
down_revision: str | None = "0028_ctrl_policy_replay_auth"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("""
        CREATE OR REPLACE FUNCTION request_engine.read_onboarding_identity_facts(
            p_organization_id uuid
        ) RETURNS jsonb
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $$
        DECLARE
            v_org_id uuid := request_engine.current_organization_id();
            v_active_controller_id uuid;
            v_effective_controller_id uuid;
            v_policy_subject_id uuid;
            v_recorded_policy_key text;
            v_policy_revision integer;
            v_policy_grants jsonb;
            v_policy_ready boolean := false;
            v_staff_available boolean := false;
            v_authority_revision bigint;
        BEGIN
            IF p_organization_id IS NULL OR p_organization_id IS DISTINCT FROM v_org_id THEN
                RAISE EXCEPTION 'Onboarding identity facts are tenant-scoped'
                    USING ERRCODE = '42501';
            END IF;

            SELECT membership.principal_id INTO v_active_controller_id
              FROM request_engine.staff_memberships AS membership
              JOIN request_engine.principals AS principal
                ON principal.id = membership.principal_id
               AND principal.principal_plane = 'tenant' AND principal.active
             WHERE membership.organization_id = p_organization_id
               AND membership.status = 'active'
               AND (SELECT count(DISTINCT grant_row.capability_key)
                      FROM request_engine.principal_authority_grants AS grant_row
                     WHERE grant_row.organization_id = p_organization_id
                       AND grant_row.principal_id = membership.principal_id
                       AND grant_row.status = 'active'
                       AND grant_row.capability_key IN (
                           'staff.manage_membership','staff.manage_authority','identity.bind'
                       )) = 3
             ORDER BY membership.principal_id LIMIT 1;

            SELECT membership.principal_id INTO v_effective_controller_id
              FROM request_engine.staff_memberships AS membership
             WHERE membership.organization_id = p_organization_id
               AND membership.status = 'active'
               AND request_engine.principal_is_effective_tenant_controller(
                   p_organization_id, membership.principal_id
               )
             ORDER BY membership.principal_id LIMIT 1;

            SELECT COALESCE(
                (SELECT adoption.target_policy_key
                   FROM request_engine.controller_policy_adoption_facts AS adoption
                  WHERE adoption.organization_id = p_organization_id
                  ORDER BY adoption.applied_at DESC, adoption.id DESC LIMIT 1),
                root_fact.initial_controller_policy_key
            ), root_fact.controller_principal_id
              INTO v_recorded_policy_key, v_policy_subject_id
              FROM request_engine.organization_root_provisioning_facts AS root_fact
             WHERE root_fact.organization_id = p_organization_id;

            IF v_recorded_policy_key IS NOT NULL THEN
                SELECT policy.revision, policy.grants
                  INTO v_policy_revision, v_policy_grants
                  FROM request_engine.initial_controller_policies AS policy
                 WHERE policy.policy_key = v_recorded_policy_key;
                IF FOUND AND EXISTS (
                    SELECT 1 FROM request_engine.staff_memberships membership
                    JOIN request_engine.principals principal
                      ON principal.id=membership.principal_id
                     AND principal.principal_plane='tenant' AND principal.active
                    WHERE membership.organization_id=p_organization_id
                      AND membership.principal_id=v_policy_subject_id
                      AND membership.status='active'
                ) THEN
                    v_policy_ready := NOT EXISTS (
                        SELECT 1 FROM jsonb_to_recordset(v_policy_grants)
                            AS g(capability_key text, authority_plane text, delegable boolean)
                         WHERE NOT EXISTS (
                             SELECT 1 FROM request_engine.principal_authority_grants AS active
                              WHERE active.organization_id = p_organization_id
                                AND active.principal_id = v_policy_subject_id
                                AND active.capability_key = g.capability_key
                                AND active.authority_plane = g.authority_plane
                                AND active.delegable = g.delegable
                                AND active.status = 'active'
                         )
                    );
                END IF;
            END IF;

            SELECT EXISTS (
                SELECT 1
                  FROM request_engine.principal_authority_grants AS membership_grant
                  JOIN request_engine.principal_authority_grants AS authority_grant
                    ON authority_grant.organization_id = membership_grant.organization_id
                   AND authority_grant.principal_id = membership_grant.principal_id
                   AND authority_grant.capability_key = 'staff.manage_authority'
                   AND authority_grant.status = 'active'
                  JOIN request_engine.principals AS principal
                    ON principal.id = membership_grant.principal_id
                   AND principal.principal_plane = 'tenant' AND principal.active
                 WHERE membership_grant.organization_id = p_organization_id
                   AND membership_grant.capability_key = 'staff.manage_membership'
                   AND membership_grant.status = 'active'
            ) INTO v_staff_available;

            -- This revision accompanies current_policy_ready, which is evaluated
            -- against the immutable original controller. Do not report another
            -- active controller's revision for that policy subject.
            IF v_policy_subject_id IS NOT NULL THEN
                SELECT principal.authority_revision INTO v_authority_revision
                  FROM request_engine.principals AS principal
                 WHERE principal.id = v_policy_subject_id;
            END IF;

            RETURN jsonb_build_object(
                'identity', jsonb_build_object(
                    'active_controller', v_active_controller_id IS NOT NULL,
                    'authenticatable_controller', v_effective_controller_id IS NOT NULL
                ),
                'tenant_control', jsonb_build_object(
                    'current_policy_ready', v_policy_ready,
                    'recorded_policy_key', v_recorded_policy_key
                ),
                'staff_administration', jsonb_build_object('available', v_staff_available),
                'observed_at', to_char(clock_timestamp() AT TIME ZONE 'UTC',
                    'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
                'controller_authority_revision', v_authority_revision,
                'policy_revision', v_policy_revision
            );
        END
        $$;
    """)


def downgrade() -> None:
    raise RuntimeError("Onboarding readiness semantics are roll-forward only")
