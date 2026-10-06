"""Narrow policy-adoption definer access to columns used by its commands."""

from alembic import op

revision: str = "0032_adopt_column_acls"
down_revision: str | None = "0031_adopt_approver_scope"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("""
        CREATE OR REPLACE FUNCTION request_platform.apply_controller_policy_adoption(
            p_request_id uuid,p_expected_revision bigint,p_key_digest text,p_intent_digest text)
        RETURNS TABLE(fact_id uuid,request_id uuid,organization_id uuid,
            controller_principal_id uuid,
            source_policy_key text,target_policy_key text,authority_revision_before bigint,
            authority_revision_after bigint,added_capabilities text[],request_revision bigint,
            platform_approver_principal_id uuid,platform_authority_revision bigint,
            applied_at timestamptz)
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path=pg_catalog,request_engine,request_platform,pg_temp AS $$
        DECLARE
            v_actor uuid;
            v_actor_revision bigint;
            v_actor_binding uuid;
            v_actor_authority uuid;
            v_actor_subject text;
            v_root_authority uuid;
            v_root_subject text;
            v_org uuid;
            v_root uuid;
            v_binding uuid;
            v_source text;
            v_target jsonb;
            v_before bigint;
            v_after bigint;
            v_added text[];
            v_request record;
            v_replay record;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
            v_actor:=NULLIF(current_setting(
                'request_engine.authenticated_principal_id',true),'')::uuid;
            v_actor_revision:=NULLIF(current_setting(
                'request_engine.authority_revision',true),'')::bigint;
            IF v_actor IS NULL OR v_actor_revision IS NULL THEN
                RAISE EXCEPTION 'Current platform HUMAN authority is required'
                    USING ERRCODE='42501';
            END IF;
            SELECT p.authority_revision INTO v_actor_revision
              FROM request_engine.principals p
             WHERE p.id=v_actor AND p.principal_plane='platform'
               AND p.principal_kind='human' AND p.active FOR SHARE;
            IF NOT FOUND OR v_actor_revision IS DISTINCT FROM NULLIF(
                current_setting('request_engine.authority_revision',true),'')::bigint
               OR NOT EXISTS(
                SELECT 1 FROM request_engine.principals p
                JOIN request_engine.principal_authority_grants g ON g.principal_id=p.id
               WHERE p.id=v_actor AND p.principal_plane='platform' AND p.principal_kind='human'
                 AND p.active AND p.authority_revision=v_actor_revision
                 AND g.principal_plane='platform' AND g.authority_plane='platform'
                 AND g.capability_key='platform.organization.adopt_initial_controller_policy'
                 AND g.status='active') THEN
                RAISE EXCEPTION 'Current Platform Owner lacks policy-adoption authority'
                    USING ERRCODE='42501';
            END IF;
            IF p_expected_revision IS NULL OR p_expected_revision<1
               OR p_key_digest !~ '^[0-9a-f]{64}$' OR p_intent_digest !~ '^[0-9a-f]{64}$' THEN
                RAISE EXCEPTION 'Invalid adoption application input' USING ERRCODE='22023';
            END IF;
            SELECT r.organization_id INTO v_org
              FROM request_engine.controller_policy_adoption_requests r WHERE r.id=p_request_id;
            IF NOT FOUND THEN RAISE EXCEPTION 'Adoption request unavailable'
                USING ERRCODE='P0002'; END IF;
            PERFORM set_config('request_engine.organization_id',v_org::text,true);
            PERFORM request_engine.lock_tenant_staff_root();
            PERFORM m.id FROM request_engine.staff_memberships m
             WHERE m.organization_id=v_org AND m.status='active'
             ORDER BY m.principal_id FOR UPDATE;
            SELECT r.id,r.organization_id,r.controller_principal_id,r.controller_binding_id,
                   r.source_policy_key,r.target_policy_key,r.expected_authority_revision,
                   r.reason,r.status,r.revision,r.created_at,r.expires_at
              INTO v_request
              FROM request_engine.controller_policy_adoption_requests r
             WHERE r.id=p_request_id FOR UPDATE;
            IF NOT FOUND THEN RAISE EXCEPTION 'Adoption request unavailable'
                USING ERRCODE='P0002'; END IF;
            IF v_org IS DISTINCT FROM v_request.organization_id THEN
                RAISE EXCEPTION 'Adoption request scope changed' USING ERRCODE='40001';
            END IF;
            IF EXISTS(SELECT 1 FROM request_engine.controller_policy_adoption_facts f
                WHERE f.request_id=p_request_id) THEN
                SELECT f.id,f.request_id,f.organization_id,f.controller_principal_id,
                       f.source_policy_key,f.target_policy_key,f.authority_revision_before,
                       f.authority_revision_after,f.added_capabilities,
                       f.idempotency_key_digest,f.intent_digest,
                       f.platform_approver_principal_id,f.platform_authority_revision,f.applied_at
                  INTO v_replay
                  FROM request_engine.controller_policy_adoption_facts f
                 WHERE f.request_id=p_request_id;
                IF v_replay.platform_approver_principal_id<>v_actor
                   OR v_replay.idempotency_key_digest<>p_key_digest
                   OR v_replay.intent_digest<>p_intent_digest THEN
                    RAISE EXCEPTION 'Adoption has already been applied' USING ERRCODE='23505';
                END IF;
                RETURN QUERY SELECT v_replay.id,v_replay.request_id,v_replay.organization_id,
                    v_replay.controller_principal_id,v_replay.source_policy_key,
                    v_replay.target_policy_key,v_replay.authority_revision_before,
                    v_replay.authority_revision_after,v_replay.added_capabilities,
                    v_request.revision,v_replay.platform_approver_principal_id,
                    v_replay.platform_authority_revision,v_replay.applied_at;
                RETURN;
            END IF;
            IF v_request.status<>'pending' OR v_request.expires_at<=clock_timestamp()
               OR v_request.revision<>p_expected_revision THEN
                RAISE EXCEPTION 'Consent is expired, withdrawn, or stale' USING ERRCODE='40001';
            END IF;
            SELECT f.controller_principal_id,f.controller_binding_id,
                   COALESCE((SELECT fact.target_policy_key
                      FROM request_engine.controller_policy_adoption_facts fact
                      WHERE fact.organization_id=v_org
                      ORDER BY fact.applied_at DESC,fact.id DESC LIMIT 1),
                      f.initial_controller_policy_key)
              INTO v_root,v_binding,v_source
              FROM request_engine.organization_root_provisioning_facts f
             WHERE f.organization_id=v_org;
            IF NOT FOUND OR v_root<>v_request.controller_principal_id
               OR v_binding<>v_request.controller_binding_id
               OR v_source<>v_request.source_policy_key
               OR v_actor=v_root THEN
                RAISE EXCEPTION 'Root consent, source policy or distinct HUMAN identity changed'
                    USING ERRCODE='42501';
            END IF;
            v_actor_binding:=NULLIF(current_setting('request_engine.identity_binding_id',true),'')::uuid;
            IF v_actor_binding IS NULL THEN
                RAISE EXCEPTION 'Bound Platform identity is required' USING ERRCODE='42501';
            END IF;
            SELECT b.identity_authority_id,b.subject_id INTO v_root_authority,v_root_subject
              FROM request_engine.identity_bindings b
             WHERE b.id=v_binding AND b.organization_id=v_org AND b.principal_id=v_root
               AND b.principal_plane='tenant' AND b.status='active' FOR SHARE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Original controller is no longer active' USING ERRCODE='42501';
            END IF;
            SELECT b.identity_authority_id,b.subject_id INTO v_actor_authority,v_actor_subject
              FROM request_engine.identity_bindings b
             WHERE b.id=v_actor_binding AND b.principal_id=v_actor
               AND b.principal_plane='platform'
               AND b.organization_id IS NULL AND b.status='active' FOR SHARE;
            IF NOT FOUND OR (v_actor_authority=v_root_authority
                AND v_actor_subject=v_root_subject) THEN
                RAISE EXCEPTION 'Application requires a distinct active native HUMAN identity'
                    USING ERRCODE='42501';
            END IF;
            IF NOT EXISTS(SELECT 1 FROM request_engine.identity_bindings b
                 JOIN request_engine.principals p ON p.id=b.principal_id
                WHERE b.id=v_binding AND b.organization_id=v_org AND b.principal_id=v_root
                  AND b.principal_plane='tenant' AND b.status='active'
                  AND p.organization_id=v_org AND p.principal_plane='tenant'
                  AND p.principal_kind='human' AND p.active) THEN
                RAISE EXCEPTION 'Original controller is no longer active' USING ERRCODE='42501';
            END IF;
            SELECT p.authority_revision INTO v_before FROM request_engine.principals p
             WHERE p.id=v_root AND p.organization_id=v_org FOR UPDATE;
            IF v_before<>v_request.expected_authority_revision THEN
                RAISE EXCEPTION 'Tenant controller authority changed after consent'
                    USING ERRCODE='40001';
            END IF;
            SELECT grants INTO v_target FROM request_engine.initial_controller_policies
             WHERE policy_key=v_request.target_policy_key;
            IF NOT FOUND OR v_request.target_policy_key<>'tenant-controller-v6'
               OR v_request.source_policy_key NOT IN
                    ('tenant-controller-v1','tenant-controller-v2','tenant-controller-v3',
                     'tenant-controller-v4','tenant-controller-v5') THEN
                RAISE EXCEPTION 'The requested policy transition is not approved'
                    USING ERRCODE='22023';
            END IF;
            IF EXISTS(SELECT 1 FROM jsonb_to_recordset(v_target)
                AS g(capability_key text,authority_plane text,delegable boolean)
                JOIN request_engine.principal_authority_grants r
                  ON r.organization_id=v_org AND r.principal_id=v_root
                 AND r.capability_key=g.capability_key AND r.status='revoked'
                WHERE NOT EXISTS(SELECT 1 FROM request_engine.principal_authority_grants a
                    WHERE a.organization_id=v_org AND a.principal_id=v_root
                      AND a.capability_key=g.capability_key AND a.status='active')) THEN
                RAISE EXCEPTION 'Policy adoption cannot restore revoked tenant authority'
                    USING ERRCODE='23514';
            END IF;
            SELECT COALESCE(array_agg(g.capability_key ORDER BY g.capability_key),ARRAY[]::text[])
              INTO v_added FROM jsonb_to_recordset(v_target)
                AS g(capability_key text,authority_plane text,delegable boolean)
             WHERE NOT EXISTS(SELECT 1 FROM request_engine.principal_authority_grants a
                 WHERE a.organization_id=v_org AND a.principal_id=v_root
                   AND a.capability_key=g.capability_key AND a.status='active');
            IF cardinality(v_added)=0 THEN
                RAISE EXCEPTION 'No policy capabilities are missing' USING ERRCODE='55000';
            END IF;
            INSERT INTO request_engine.principal_authority_grants(
                organization_id,principal_id,principal_plane,authority_plane,capability_key,
                delegable,granted_by_principal_id,provenance_kind,provenance_reference)
            SELECT v_org,v_root,'tenant',g.authority_plane,g.capability_key,g.delegable,
                v_actor,'controller_policy_adoption','adoption:'||p_request_id::text
              FROM jsonb_to_recordset(v_target)
                AS g(capability_key text,authority_plane text,delegable boolean)
             WHERE g.capability_key=ANY(v_added);
            SELECT p.authority_revision INTO v_after FROM request_engine.principals p
             WHERE p.id=v_root AND p.organization_id=v_org;
            INSERT INTO request_engine.controller_policy_adoption_facts AS inserted_fact(
                request_id,organization_id,controller_principal_id,controller_binding_id,
                platform_approver_principal_id,source_policy_key,target_policy_key,
                authority_revision_before,authority_revision_after,added_capabilities,
                idempotency_key_digest,intent_digest,platform_authority_revision,correlation_id)
            VALUES(p_request_id,v_org,v_root,v_binding,v_actor,v_source,v_request.target_policy_key,
                v_before,v_after,v_added,p_key_digest,p_intent_digest,v_actor_revision,
                NULLIF(current_setting('request_engine.correlation_id',true),'')::uuid)
            RETURNING inserted_fact.id,inserted_fact.applied_at INTO fact_id,applied_at;
            UPDATE request_engine.controller_policy_adoption_requests r SET status='applied',
                revision=revision+1,closed_at=clock_timestamp()
             WHERE r.id=p_request_id RETURNING r.revision INTO request_revision;
            request_id:=p_request_id; organization_id:=v_org; controller_principal_id:=v_root;
            source_policy_key:=v_source; target_policy_key:=v_request.target_policy_key;
            authority_revision_before:=v_before; authority_revision_after:=v_after;
            added_capabilities:=v_added; platform_approver_principal_id:=v_actor;
            platform_authority_revision:=v_actor_revision; RETURN NEXT;
        END $$;
        ALTER FUNCTION request_platform.apply_controller_policy_adoption(uuid,bigint,text,text)
            OWNER TO request_platform_control_definer;
        REVOKE ALL ON FUNCTION request_platform.apply_controller_policy_adoption(
            uuid,bigint,text,text) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_platform.apply_controller_policy_adoption(
            uuid,bigint,text,text) TO request_platform_control;

        CREATE OR REPLACE FUNCTION request_platform.review_controller_policy_adoption(
            p_request_id uuid)
        RETURNS TABLE(request_id uuid,organization_id uuid,controller_principal_id uuid,
            source_policy_key text,target_policy_key text,expected_authority_revision bigint,
            request_revision bigint,reason text,created_at timestamptz,expires_at timestamptz,
            current_authority_revision bigint,proposed_capabilities text[],
            revoked_capabilities text[])
        LANGUAGE plpgsql STABLE SECURITY DEFINER
        SET search_path=pg_catalog,request_engine,request_platform,pg_temp AS $$
        DECLARE
            v_actor uuid;
            v_actor_revision bigint;
            v_actor_binding uuid;
            v_request record;
            v_authority_revision bigint;
            v_target jsonb;
        BEGIN
            v_actor:=NULLIF(current_setting(
                'request_engine.authenticated_principal_id',true),'')::uuid;
            v_actor_revision:=NULLIF(current_setting(
                'request_engine.authority_revision',true),'')::bigint;
            v_actor_binding:=NULLIF(current_setting(
                'request_engine.identity_binding_id',true),'')::uuid;
            IF v_actor IS NULL OR v_actor_revision IS NULL OR v_actor_binding IS NULL
               OR NOT EXISTS(
                   SELECT 1 FROM request_engine.principals p
                   JOIN request_engine.identity_bindings b ON b.id=v_actor_binding
                     AND b.principal_id=p.id AND b.principal_plane='platform'
                     AND b.organization_id IS NULL AND b.status='active'
                   JOIN request_engine.principal_authority_grants g ON g.principal_id=p.id
                   WHERE p.id=v_actor AND p.principal_plane='platform'
                     AND p.principal_kind='human' AND p.active
                     AND p.authority_revision=v_actor_revision
                     AND g.principal_plane='platform' AND g.authority_plane='platform'
                     AND g.capability_key='platform.organization.adopt_initial_controller_policy'
                     AND g.status='active'
               ) THEN
                RAISE EXCEPTION 'Current Platform Owner may not review adoption'
                    USING ERRCODE='42501';
            END IF;
            SELECT r.id,r.organization_id,r.controller_principal_id,r.source_policy_key,
                   r.target_policy_key,r.expected_authority_revision,r.revision,r.reason,
                   r.created_at,r.expires_at
              INTO v_request
              FROM request_engine.controller_policy_adoption_requests r
             WHERE r.id=p_request_id AND r.status='pending'
               AND r.expires_at>clock_timestamp();
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Adoption request unavailable' USING ERRCODE='P0002';
            END IF;
            SELECT p.authority_revision INTO v_authority_revision
              FROM request_engine.principals p
             WHERE p.id=v_request.controller_principal_id
               AND p.organization_id=v_request.organization_id AND p.active;
            IF NOT FOUND OR v_authority_revision<>v_request.expected_authority_revision THEN
                RAISE EXCEPTION 'Consenting controller authority has changed' USING ERRCODE='40001';
            END IF;
            SELECT p.grants INTO v_target FROM request_engine.initial_controller_policies p
             WHERE p.policy_key=v_request.target_policy_key;
            RETURN QUERY SELECT v_request.id,v_request.organization_id,
                v_request.controller_principal_id,v_request.source_policy_key,
                v_request.target_policy_key,v_request.expected_authority_revision,
                v_request.revision,v_request.reason,v_request.created_at,v_request.expires_at,
                v_authority_revision,
                COALESCE((SELECT array_agg(g.capability_key ORDER BY g.capability_key)
                  FROM jsonb_to_recordset(v_target)
                    AS g(capability_key text,authority_plane text,delegable boolean)
                 WHERE NOT EXISTS(SELECT 1 FROM request_engine.principal_authority_grants a
                    WHERE a.organization_id=v_request.organization_id
                      AND a.principal_id=v_request.controller_principal_id
                      AND a.capability_key=g.capability_key AND a.status='active')),
                    ARRAY[]::text[]),
                COALESCE((SELECT array_agg(g.capability_key ORDER BY g.capability_key)
                  FROM jsonb_to_recordset(v_target)
                    AS g(capability_key text,authority_plane text,delegable boolean)
                 WHERE EXISTS(SELECT 1 FROM request_engine.principal_authority_grants r
                    WHERE r.organization_id=v_request.organization_id
                      AND r.principal_id=v_request.controller_principal_id
                      AND r.capability_key=g.capability_key AND r.status='revoked')
                   AND NOT EXISTS(SELECT 1 FROM request_engine.principal_authority_grants a
                    WHERE a.organization_id=v_request.organization_id
                      AND a.principal_id=v_request.controller_principal_id
                      AND a.capability_key=g.capability_key AND a.status='active')),
                    ARRAY[]::text[]);
        END $$;
        ALTER FUNCTION request_platform.review_controller_policy_adoption(uuid)
            OWNER TO request_platform_control_definer;
        REVOKE ALL ON FUNCTION request_platform.review_controller_policy_adoption(uuid)
            FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_platform.review_controller_policy_adoption(uuid)
            TO request_platform_control;

        REVOKE SELECT,UPDATE ON request_engine.controller_policy_adoption_requests
            FROM request_platform_control_definer;
        GRANT SELECT(id,organization_id,controller_principal_id,controller_binding_id,
            source_policy_key,target_policy_key,expected_authority_revision,reason,status,
            revision,created_at,expires_at)
            ON request_engine.controller_policy_adoption_requests
            TO request_platform_control_definer;
        GRANT UPDATE(status,revision,closed_at)
            ON request_engine.controller_policy_adoption_requests
            TO request_platform_control_definer;

        REVOKE SELECT,INSERT ON request_engine.controller_policy_adoption_facts
            FROM request_platform_control_definer;
        GRANT SELECT(id,request_id,organization_id,controller_principal_id,source_policy_key,
            target_policy_key,authority_revision_before,authority_revision_after,
            added_capabilities,idempotency_key_digest,intent_digest,
            platform_approver_principal_id,platform_authority_revision,applied_at)
            ON request_engine.controller_policy_adoption_facts
            TO request_platform_control_definer;
        GRANT INSERT(request_id,organization_id,controller_principal_id,controller_binding_id,
            platform_approver_principal_id,source_policy_key,target_policy_key,
            authority_revision_before,authority_revision_after,added_capabilities,
            idempotency_key_digest,intent_digest,platform_authority_revision,correlation_id)
            ON request_engine.controller_policy_adoption_facts
            TO request_platform_control_definer;
    """)


def downgrade() -> None:
    raise RuntimeError("Controller policy adoption ACL narrowing is roll-forward only")
