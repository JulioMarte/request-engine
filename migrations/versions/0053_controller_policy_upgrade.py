"""Governed tenant-controller policy upgrade with a delegable ceiling.

Block E1 of ``docs/architecture/auth-production-completion-plan.md``. Appends an
immutable ``tenant-controller-v4`` catalog row (v3 plus the dedicated
``controller_policy_upgrade`` tenant-control capability) and the tenant-control
command ``request_engine.upgrade_controller_policy``. The command resolves both
policy keys against the immutable catalog, requires the actor's current
delegable ceiling for every missing capability, refuses to resurrect a revoked
grant and refuses self-elevation. No existing root is backfilled.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0053_controller_policy_upgrade"
down_revision: str | Sequence[str] | None = "0052_issuance_reservation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("""
        INSERT INTO request_engine.initial_controller_policies (policy_key, revision, grants)
        SELECT 'tenant-controller-v4', 4, grants ||
            '[{"capability_key": "controller_policy_upgrade",
               "authority_plane": "tenant_control", "delegable": true}]'::jsonb
          FROM request_engine.initial_controller_policies WHERE policy_key='tenant-controller-v3'
    """)
    op.execute(
        r"""
CREATE FUNCTION request_engine.upgrade_controller_policy(
    p_target_principal_id uuid,
    p_source_policy_key text,
    p_target_policy_key text,
    p_expected_authority_revision bigint,
    p_provenance_reference text
)
 RETURNS bigint
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
AS $function$
        DECLARE
            v_actor_id uuid;
            v_org_id uuid := request_engine.current_organization_id();
            v_target_grants jsonb;
            v_current_revision bigint;
            v_root_controller_id uuid;
            v_root_policy_key text;
            v_grant record;
            v_actor_plane text;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
            PERFORM request_engine.lock_tenant_staff_root();
            v_actor_id := request_engine.assert_staff_manager(
                'controller_policy_upgrade'
            );

            IF p_target_principal_id IS NULL
               OR p_target_policy_key IS NULL
               OR length(btrim(p_target_policy_key)) = 0
               OR p_expected_authority_revision IS NULL
               OR p_expected_authority_revision < 1
               OR p_provenance_reference IS NULL
               OR length(btrim(p_provenance_reference)) = 0
            THEN
                RAISE EXCEPTION 'Controller policy upgrade input is invalid'
                    USING ERRCODE = '22023';
            END IF;

            SELECT grants INTO v_target_grants
              FROM request_engine.initial_controller_policies
             WHERE policy_key = p_target_policy_key;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Unknown controller policy'
                    USING ERRCODE = '22023';
            END IF;

            IF p_source_policy_key IS NOT NULL
               AND length(btrim(p_source_policy_key)) > 0
            THEN
                SELECT root_fact.controller_principal_id,
                       root_fact.initial_controller_policy_key
                  INTO v_root_controller_id, v_root_policy_key
                  FROM request_engine.organization_root_provisioning_facts AS root_fact
                 WHERE root_fact.organization_id = v_org_id;
                IF v_root_controller_id = p_target_principal_id
                   AND v_root_policy_key IS NOT NULL
                   AND v_root_policy_key IS DISTINCT FROM btrim(p_source_policy_key)
                THEN
                    RAISE EXCEPTION 'Controller policy source assertion is stale'
                        USING ERRCODE = '40001';
                END IF;
            END IF;

            SELECT authority_revision INTO v_current_revision
              FROM request_engine.principals
             WHERE id = p_target_principal_id
               AND organization_id = v_org_id
               AND principal_plane = 'tenant'
               AND active
             FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Target Principal is not visible in this tenant'
                    USING ERRCODE = 'P0002';
            END IF;
            IF v_current_revision <> p_expected_authority_revision THEN
                RAISE EXCEPTION 'Controller policy revision is stale'
                    USING ERRCODE = '40001';
            END IF;
            IF p_target_principal_id = v_actor_id THEN
                RAISE EXCEPTION 'Controller policy self-upgrade is forbidden'
                    USING ERRCODE = '42501';
            END IF;

            IF EXISTS (
                SELECT 1
                  FROM jsonb_to_recordset(v_target_grants)
                    AS g(capability_key text, authority_plane text, delegable boolean)
                 WHERE EXISTS (
                           SELECT 1
                             FROM request_engine.principal_authority_grants AS revoked
                            WHERE revoked.organization_id = v_org_id
                              AND revoked.principal_id = p_target_principal_id
                              AND revoked.capability_key = g.capability_key
                              AND revoked.status = 'revoked'
                       )
                   AND NOT EXISTS (
                           SELECT 1
                             FROM request_engine.principal_authority_grants AS active
                            WHERE active.organization_id = v_org_id
                              AND active.principal_id = p_target_principal_id
                              AND active.capability_key = g.capability_key
                              AND active.status = 'active'
                       )
            ) THEN
                RAISE EXCEPTION 'Controller policy upgrade cannot restore revoked authority'
                    USING ERRCODE = '23514';
            END IF;

            FOR v_grant IN
                SELECT g.capability_key
                  FROM jsonb_to_recordset(v_target_grants)
                    AS g(capability_key text, authority_plane text, delegable boolean)
                 WHERE NOT EXISTS (
                           SELECT 1
                             FROM request_engine.principal_authority_grants AS active
                            WHERE active.organization_id = v_org_id
                              AND active.principal_id = p_target_principal_id
                              AND active.capability_key = g.capability_key
                              AND active.status = 'active'
                       )
            LOOP
                SELECT grant_row.authority_plane INTO v_actor_plane
                  FROM request_engine.principal_authority_grants AS grant_row
                 WHERE grant_row.organization_id = v_org_id
                   AND grant_row.principal_id = v_actor_id
                   AND grant_row.capability_key = v_grant.capability_key
                   AND grant_row.status = 'active'
                   AND grant_row.delegable
                 FOR SHARE;
                IF NOT FOUND OR v_actor_plane = 'platform' THEN
                    RAISE EXCEPTION 'Controller policy upgrade exceeds delegable ceiling'
                        USING ERRCODE = '42501';
                END IF;
            END LOOP;

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
            )
            SELECT v_org_id,
                   p_target_principal_id,
                   'tenant',
                   g.authority_plane,
                   g.capability_key,
                   false,
                   v_actor_id,
                   'controller_policy_upgrade',
                   btrim(p_provenance_reference)
              FROM jsonb_to_recordset(v_target_grants)
                AS g(capability_key text, authority_plane text, delegable boolean)
             WHERE NOT EXISTS (
                       SELECT 1
                         FROM request_engine.principal_authority_grants AS active
                        WHERE active.organization_id = v_org_id
                          AND active.principal_id = p_target_principal_id
                          AND active.capability_key = g.capability_key
                          AND active.status = 'active'
                   );

            SELECT authority_revision INTO v_current_revision
              FROM request_engine.principals
             WHERE id = p_target_principal_id;
            RETURN v_current_revision;
        END
        $function$;
        ALTER FUNCTION request_engine.upgrade_controller_policy(
            uuid, text, text, bigint, text
        ) OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_engine.upgrade_controller_policy(
            uuid, text, text, bigint, text
        ) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_engine.upgrade_controller_policy(
            uuid, text, text, bigint, text
        ) TO request_engine_app;
        """
    )


def downgrade() -> None:
    raise RuntimeError("Controller policy catalog provenance is append-only; roll forward")
