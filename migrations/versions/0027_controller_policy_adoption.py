"""Add a dual-consent, bounded legacy controller policy adoption journey.

No existing tenant grant, revision, identity or root provisioning fact is
changed by installing this migration. Adoption is opt-in and records the
original root's consent separately from the Platform Owner's application.
"""

from alembic import op

revision: str = "0027_controller_policy_adoption"
down_revision: str | None = "0026_platform_owner_v5"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE request_engine.controller_policy_adoption_requests (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            organization_id uuid NOT NULL REFERENCES request_engine.organizations(id),
            controller_principal_id uuid NOT NULL REFERENCES request_engine.principals(id),
            controller_binding_id uuid NOT NULL REFERENCES request_engine.identity_bindings(id),
            source_policy_key text NOT NULL,
            target_policy_key text NOT NULL CHECK(target_policy_key='tenant-controller-v6'),
            expected_authority_revision bigint NOT NULL CHECK(expected_authority_revision>0),
            reason text NOT NULL CHECK(length(btrim(reason)) BETWEEN 1 AND 500),
            idempotency_key_digest text NOT NULL CHECK(idempotency_key_digest ~ '^[0-9a-f]{64}$'),
            intent_digest text NOT NULL CHECK(intent_digest ~ '^[0-9a-f]{64}$'),
            withdrawn_key_digest text,
            withdrawn_intent_digest text,
            correlation_id uuid NOT NULL,
            status text NOT NULL DEFAULT 'pending'
            CHECK(status IN ('pending','withdrawn','expired','applied')),
            revision bigint NOT NULL DEFAULT 1 CHECK(revision>0),
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            expires_at timestamptz NOT NULL,
            closed_at timestamptz,
            CONSTRAINT controller_policy_adoption_request_time_ck
                CHECK(expires_at > created_at AND expires_at <= created_at + interval '24 hours'),
            CONSTRAINT controller_policy_adoption_withdrawal_shape_ck CHECK(
                (status='withdrawn') = (closed_at IS NOT NULL AND withdrawn_key_digest IS NOT NULL
                  AND withdrawn_intent_digest IS NOT NULL)
                OR (status<>'withdrawn' AND withdrawn_key_digest IS NULL
                  AND withdrawn_intent_digest IS NULL)),
            CONSTRAINT controller_policy_adoption_status_time_ck CHECK(
                (status='pending' AND closed_at IS NULL) OR
                (status IN ('withdrawn','expired','applied') AND closed_at IS NOT NULL)),
            UNIQUE(id, organization_id),
            UNIQUE(controller_principal_id, idempotency_key_digest)
        );
        CREATE UNIQUE INDEX one_pending_controller_policy_adoption_per_org
            ON request_engine.controller_policy_adoption_requests(organization_id)
            WHERE status='pending';
        CREATE INDEX controller_policy_adoption_pending_order
            ON request_engine.controller_policy_adoption_requests(created_at,id)
            WHERE status='pending';

        CREATE TABLE request_engine.controller_policy_adoption_facts (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            request_id uuid NOT NULL UNIQUE,
            organization_id uuid NOT NULL,
            controller_principal_id uuid NOT NULL,
            controller_binding_id uuid NOT NULL,
            platform_approver_principal_id uuid NOT NULL,
            source_policy_key text NOT NULL,
            target_policy_key text NOT NULL CHECK(target_policy_key='tenant-controller-v6'),
            authority_revision_before bigint NOT NULL CHECK(authority_revision_before>0),
            authority_revision_after bigint NOT NULL
                CHECK(authority_revision_after>authority_revision_before),
            added_capabilities text[] NOT NULL CHECK(cardinality(added_capabilities)>0),
            idempotency_key_digest text NOT NULL CHECK(idempotency_key_digest ~ '^[0-9a-f]{64}$'),
            intent_digest text NOT NULL CHECK(intent_digest ~ '^[0-9a-f]{64}$'),
            platform_authority_revision bigint NOT NULL CHECK(platform_authority_revision>0),
            correlation_id uuid NOT NULL,
            applied_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            CONSTRAINT controller_policy_adoption_fact_request_fk
                FOREIGN KEY(request_id,organization_id)
                REFERENCES request_engine.controller_policy_adoption_requests(id,organization_id),
            CONSTRAINT controller_policy_adoption_fact_requester_fk
                FOREIGN KEY(controller_principal_id)
                REFERENCES request_engine.principals(id),
            CONSTRAINT controller_policy_adoption_fact_binding_fk FOREIGN KEY(controller_binding_id)
                REFERENCES request_engine.identity_bindings(id),
            CONSTRAINT controller_policy_adoption_fact_approver_fk
                FOREIGN KEY(platform_approver_principal_id)
                REFERENCES request_engine.principals(id)
        );
        ALTER TABLE request_engine.controller_policy_adoption_requests
            OWNER TO request_engine_schema_owner;
        ALTER TABLE request_engine.controller_policy_adoption_facts
            OWNER TO request_engine_schema_owner;
        ALTER TABLE request_engine.controller_policy_adoption_requests ENABLE ROW LEVEL SECURITY;
        ALTER TABLE request_engine.controller_policy_adoption_requests FORCE ROW LEVEL SECURITY;
        CREATE POLICY controller_policy_adoption_tenant_isolation
            ON request_engine.controller_policy_adoption_requests
            USING(organization_id=request_engine.current_organization_id())
            WITH CHECK(organization_id=request_engine.current_organization_id());
        CREATE POLICY controller_policy_adoption_platform_control
            ON request_engine.controller_policy_adoption_requests
            TO request_platform_control_definer USING(true) WITH CHECK(true);
        CREATE POLICY identity_bindings_platform_control_read
            ON request_engine.identity_bindings
            FOR SELECT TO request_platform_control_definer
            USING(principal_plane='platform' AND organization_id IS NULL);
        GRANT SELECT(id,principal_id,principal_plane,identity_authority_id,subject_id,status)
            ON request_engine.identity_bindings TO request_platform_control_definer;
        GRANT SELECT(initial_controller_policy_key)
            ON request_engine.organization_root_provisioning_facts
            TO request_platform_control_definer;
        GRANT SELECT(policy_key,grants) ON request_engine.initial_controller_policies
            TO request_platform_control_definer;
        GRANT SELECT(organization_id,principal_id,principal_plane,authority_plane,
            capability_key,status,delegable) ON request_engine.principal_authority_grants
            TO request_platform_control_definer;
        GRANT INSERT(organization_id,principal_id,principal_plane,authority_plane,
            capability_key,delegable,granted_by_principal_id,provenance_kind,
            provenance_reference) ON request_engine.principal_authority_grants
            TO request_platform_control_definer;
        CREATE POLICY staff_memberships_platform_adoption_read
            ON request_engine.staff_memberships
            FOR SELECT TO request_platform_control_definer
            USING(organization_id=request_engine.current_organization_id());
        CREATE POLICY staff_memberships_platform_adoption_lock
            ON request_engine.staff_memberships
            FOR UPDATE TO request_platform_control_definer
            USING(organization_id=request_engine.current_organization_id())
            WITH CHECK(organization_id=request_engine.current_organization_id());
        GRANT SELECT(id,organization_id,principal_id,status)
            ON request_engine.staff_memberships TO request_platform_control_definer;
        GRANT UPDATE(id) ON request_engine.staff_memberships
            TO request_platform_control_definer;
        ALTER TABLE request_engine.controller_policy_adoption_facts ENABLE ROW LEVEL SECURITY;
        ALTER TABLE request_engine.controller_policy_adoption_facts FORCE ROW LEVEL SECURITY;
        CREATE POLICY controller_policy_adoption_fact_owner_only
            ON request_engine.controller_policy_adoption_facts
            TO request_engine_schema_owner USING(true) WITH CHECK(true);
        CREATE POLICY controller_policy_adoption_fact_platform_control
            ON request_engine.controller_policy_adoption_facts
            TO request_platform_control_definer USING(true) WITH CHECK(true);
        CREATE TRIGGER controller_policy_adoption_facts_append_only
            BEFORE UPDATE OR DELETE ON request_engine.controller_policy_adoption_facts
            FOR EACH ROW EXECUTE FUNCTION request_engine.reject_immutable_mutation();
        REVOKE ALL ON request_engine.controller_policy_adoption_requests,
            request_engine.controller_policy_adoption_facts FROM PUBLIC,request_engine_app,
            request_platform_definer,request_platform_control_definer;
        GRANT SELECT,UPDATE ON request_engine.controller_policy_adoption_requests
            TO request_platform_control_definer;
        GRANT SELECT,INSERT ON request_engine.controller_policy_adoption_facts
            TO request_platform_control_definer;
        GRANT SELECT(id,organization_id,controller_principal_id,controller_binding_id,
            source_policy_key,target_policy_key,expected_authority_revision,reason,status,
            revision,created_at,expires_at,closed_at)
            ON request_engine.controller_policy_adoption_requests TO request_engine_app;

        CREATE FUNCTION request_cmd.request_controller_policy_adoption(
            p_binding_id uuid,p_expected_authority_revision bigint,p_reason text,
            p_key_digest text,p_intent_digest text,p_correlation_id uuid)
        RETURNS TABLE(request_id uuid,source_policy_key text,target_policy_key text,
            authority_revision bigint,request_revision bigint,status text,expires_at timestamptz)
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path=pg_catalog,request_engine,request_cmd,pg_temp AS $$
        DECLARE
            v_org uuid:=request_engine.current_organization_id();
            v_actor uuid;
            v_root uuid;
            v_root_binding uuid;
            v_policy text;
            v_revision bigint;
            v_existing request_engine.controller_policy_adoption_requests%ROWTYPE;
            v_id uuid;
            v_expiry timestamptz;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
            PERFORM request_engine.lock_tenant_staff_root();
            v_actor:=request_engine.assert_staff_manager('organization.bootstrap');
            SELECT f.controller_principal_id,f.controller_binding_id,
                   COALESCE((SELECT fact.target_policy_key
                       FROM request_engine.controller_policy_adoption_facts fact
                      WHERE fact.organization_id=f.organization_id
                      ORDER BY fact.applied_at DESC,fact.id DESC LIMIT 1),
                       f.initial_controller_policy_key)
              INTO v_root,v_root_binding,v_policy
              FROM request_engine.organization_root_provisioning_facts f
             WHERE f.organization_id=v_org;
            IF NOT FOUND OR v_root IS DISTINCT FROM v_actor
               OR v_root_binding IS DISTINCT FROM p_binding_id
               OR p_binding_id IS NULL
               OR NOT EXISTS(SELECT 1 FROM request_engine.identity_bindings b
                    JOIN request_engine.principals p ON p.id=b.principal_id
                   WHERE b.id=p_binding_id AND b.organization_id=v_org
                     AND b.principal_plane='tenant' AND b.principal_id=v_actor
                     AND b.status='active' AND p.principal_plane='tenant'
                     AND p.principal_kind='human' AND p.active)
            THEN
                RAISE EXCEPTION 'Only the active original HUMAN root controller may consent'
                    USING ERRCODE='42501';
            END IF;
            IF p_expected_authority_revision IS NULL OR p_expected_authority_revision<1
               OR p_reason IS NULL OR length(btrim(p_reason)) NOT BETWEEN 1 AND 500
               OR p_key_digest !~ '^[0-9a-f]{64}$'
               OR p_intent_digest !~ '^[0-9a-f]{64}$' OR p_correlation_id IS NULL
            THEN RAISE EXCEPTION 'Invalid controller adoption request'
                USING ERRCODE='22023'; END IF;
            SELECT principal.authority_revision INTO v_revision
              FROM request_engine.principals principal
             WHERE principal.id=v_root AND principal.organization_id=v_org
               AND principal.active FOR SHARE;
            IF v_policy IS NULL OR v_policy NOT IN
                 ('tenant-controller-v1','tenant-controller-v2','tenant-controller-v3',
                  'tenant-controller-v4','tenant-controller-v5','tenant-controller-v6')
               OR NOT EXISTS(SELECT 1 FROM request_engine.initial_controller_policies
                              WHERE policy_key='tenant-controller-v6')
            THEN RAISE EXCEPTION 'No supported policy transition exists'
                USING ERRCODE='55000'; END IF;

            SELECT * INTO v_existing FROM request_engine.controller_policy_adoption_requests r
             WHERE r.controller_principal_id=v_actor AND r.idempotency_key_digest=p_key_digest;
            IF FOUND THEN
                IF v_existing.intent_digest<>p_intent_digest THEN
                    RAISE EXCEPTION 'Idempotency key conflicts' USING ERRCODE='23505';
                END IF;
                RETURN QUERY SELECT v_existing.id,v_existing.source_policy_key,
                    v_existing.target_policy_key,v_existing.expected_authority_revision,
                    v_existing.revision,v_existing.status,v_existing.expires_at;
                RETURN;
            END IF;
            IF v_policy NOT IN ('tenant-controller-v1','tenant-controller-v2',
                'tenant-controller-v3','tenant-controller-v4','tenant-controller-v5') THEN
                RAISE EXCEPTION 'No supported policy transition exists' USING ERRCODE='55000';
            END IF;
            IF v_revision IS DISTINCT FROM p_expected_authority_revision THEN
                RAISE EXCEPTION 'Controller authority changed' USING ERRCODE='40001';
            END IF;
            UPDATE request_engine.controller_policy_adoption_requests r
               SET status='expired',closed_at=clock_timestamp(),revision=revision+1
             WHERE r.organization_id=v_org AND r.status='pending'
               AND r.expires_at<=clock_timestamp();
            IF EXISTS(SELECT 1 FROM request_engine.controller_policy_adoption_requests r
                WHERE r.organization_id=v_org AND r.status='pending') THEN
                RAISE EXCEPTION 'A policy adoption request is already pending'
                    USING ERRCODE='23505';
            END IF;
            v_id:=uuidv7();
            v_expiry:=clock_timestamp()+interval '24 hours';
            INSERT INTO request_engine.controller_policy_adoption_requests(
                id,organization_id,controller_principal_id,controller_binding_id,
                source_policy_key,target_policy_key,expected_authority_revision,reason,
                idempotency_key_digest,intent_digest,correlation_id,expires_at)
            VALUES(v_id,v_org,v_actor,p_binding_id,v_policy,'tenant-controller-v6',v_revision,
                btrim(p_reason),p_key_digest,p_intent_digest,p_correlation_id,v_expiry);
            RETURN QUERY SELECT v_id,v_policy,'tenant-controller-v6',v_revision,1::bigint,
                'pending'::text,v_expiry;
        END $$;
        ALTER FUNCTION request_cmd.request_controller_policy_adoption(
            uuid,bigint,text,text,text,uuid)
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_cmd.request_controller_policy_adoption(
            uuid,bigint,text,text,text,uuid)
            FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_cmd.request_controller_policy_adoption(
            uuid,bigint,text,text,text,uuid)
            TO request_engine_app;

        CREATE FUNCTION request_cmd.withdraw_controller_policy_adoption(
            p_request_id uuid,p_expected_revision bigint,p_binding_id uuid,
            p_key_digest text,p_intent_digest text)
        RETURNS TABLE(request_revision bigint,status text)
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path=pg_catalog,request_engine,request_cmd,pg_temp AS $$
        DECLARE v_org uuid:=request_engine.current_organization_id(); v_actor uuid;
                v_root uuid; v_binding uuid;
                v_row request_engine.controller_policy_adoption_requests%ROWTYPE;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
            PERFORM request_engine.lock_tenant_staff_root();
            v_actor:=request_engine.assert_staff_manager('organization.bootstrap');
            SELECT controller_principal_id,controller_binding_id INTO v_root,v_binding
              FROM request_engine.organization_root_provisioning_facts
             WHERE organization_id=v_org;
            IF NOT FOUND OR v_root IS DISTINCT FROM v_actor
               OR v_binding IS DISTINCT FROM p_binding_id
               OR NOT EXISTS(SELECT 1 FROM request_engine.identity_bindings b
                  WHERE b.id=v_binding AND b.organization_id=v_org AND b.principal_id=v_actor
                    AND b.principal_plane='tenant' AND b.status='active') THEN
                RAISE EXCEPTION 'Only the active original root controller may withdraw consent'
                    USING ERRCODE='42501';
            END IF;
            SELECT * INTO v_row FROM request_engine.controller_policy_adoption_requests r
             WHERE r.id=p_request_id AND r.organization_id=v_org FOR UPDATE;
            IF NOT FOUND THEN RAISE EXCEPTION 'Adoption request unavailable'
                USING ERRCODE='P0002'; END IF;
            IF p_expected_revision IS NULL OR p_expected_revision<1
               OR p_key_digest !~ '^[0-9a-f]{64}$' OR p_intent_digest !~ '^[0-9a-f]{64}$' THEN
                RAISE EXCEPTION 'Invalid withdrawal input' USING ERRCODE='22023';
            END IF;
            IF v_row.status='withdrawn' AND v_row.withdrawn_key_digest=p_key_digest
               AND v_row.withdrawn_intent_digest=p_intent_digest THEN
                RETURN QUERY SELECT v_row.revision,v_row.status; RETURN;
            END IF;
            IF v_row.status<>'pending' OR v_row.expires_at<=clock_timestamp()
               OR v_row.revision<>p_expected_revision THEN
                RAISE EXCEPTION 'Adoption request is no longer withdrawable' USING ERRCODE='40001';
            END IF;
            UPDATE request_engine.controller_policy_adoption_requests r SET status='withdrawn',
                revision=revision+1,closed_at=clock_timestamp(),withdrawn_key_digest=p_key_digest,
                withdrawn_intent_digest=p_intent_digest
             WHERE r.id=p_request_id RETURNING r.revision,r.status INTO request_revision,status;
            RETURN NEXT;
        END $$;
        ALTER FUNCTION request_cmd.withdraw_controller_policy_adoption(uuid,bigint,uuid,text,text)
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_cmd.withdraw_controller_policy_adoption(
            uuid,bigint,uuid,text,text)
            FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_cmd.withdraw_controller_policy_adoption(
            uuid,bigint,uuid,text,text)
            TO request_engine_app;

        CREATE FUNCTION request_platform.apply_controller_policy_adoption(
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
            v_request request_engine.controller_policy_adoption_requests%ROWTYPE;
            v_replay request_engine.controller_policy_adoption_facts%ROWTYPE;
        BEGIN
            -- Topology is first for platform apply, followed by tenant staff roots
            -- in stable Principal order, matching tenant membership/binding writers.
            PERFORM request_engine.acquire_identity_topology_share();
            v_actor:=NULLIF(current_setting(
                'request_engine.authenticated_principal_id',true),'')::uuid;
            v_actor_revision:=NULLIF(current_setting(
                'request_engine.authority_revision',true),'')::bigint;
            IF v_actor IS NULL OR v_actor_revision IS NULL THEN
                RAISE EXCEPTION 'Current platform HUMAN authority is required'
                    USING ERRCODE='42501';
            END IF;
            -- Serialize apply against capability revocation before inspecting
            -- the grant row; the principal authority revision is the lock root.
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
            -- First read only the immutable tenant key. Lock order is then
            -- topology -> canonical tenant staff root -> ordered memberships ->
            -- request -> controller Principal/binding, matching tenant writers.
            SELECT r.organization_id INTO v_org
              FROM request_engine.controller_policy_adoption_requests r WHERE r.id=p_request_id;
            IF NOT FOUND THEN RAISE EXCEPTION 'Adoption request unavailable'
                USING ERRCODE='P0002'; END IF;
            PERFORM set_config('request_engine.organization_id',v_org::text,true);
            PERFORM request_engine.lock_tenant_staff_root();
            PERFORM m.id FROM request_engine.staff_memberships m
             WHERE m.organization_id=v_org AND m.status='active'
             ORDER BY m.principal_id FOR UPDATE;
            SELECT * INTO v_request FROM request_engine.controller_policy_adoption_requests r
             WHERE r.id=p_request_id FOR UPDATE;
            IF NOT FOUND THEN RAISE EXCEPTION 'Adoption request unavailable'
                USING ERRCODE='P0002'; END IF;
            IF v_org IS DISTINCT FROM v_request.organization_id THEN
                RAISE EXCEPTION 'Adoption request scope changed' USING ERRCODE='40001';
            END IF;
            IF EXISTS(SELECT 1 FROM request_engine.controller_policy_adoption_facts f
                WHERE f.request_id=p_request_id) THEN
                SELECT * INTO v_replay FROM request_engine.controller_policy_adoption_facts f
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
        GRANT EXECUTE ON FUNCTION request_engine.lock_tenant_staff_root()
            TO request_platform_control_definer;
        REVOKE ALL ON FUNCTION request_platform.apply_controller_policy_adoption(
            uuid,bigint,text,text)
            FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_platform.apply_controller_policy_adoption(
            uuid,bigint,text,text)
            TO request_platform_control;

        CREATE POLICY controller_policy_adoption_platform_reader
            ON request_engine.controller_policy_adoption_requests
            TO request_platform_definer USING(true);
        GRANT SELECT(id,organization_id,controller_principal_id,source_policy_key,
            target_policy_key,expected_authority_revision,status,revision,created_at,expires_at)
            ON request_engine.controller_policy_adoption_requests TO request_platform_definer;

        CREATE FUNCTION request_platform.list_controller_policy_adoptions(
            p_after uuid,p_limit integer,p_request_id uuid DEFAULT NULL)
        RETURNS TABLE(request_id uuid,organization_id uuid,controller_principal_id uuid,
            source_policy_key text,target_policy_key text,expected_authority_revision bigint,
            status text,revision bigint,created_at timestamptz,expires_at timestamptz)
        LANGUAGE plpgsql STABLE SECURITY DEFINER
        SET search_path=pg_catalog,request_engine,request_platform,pg_temp AS $$
        DECLARE v_actor uuid;
                v_revision bigint;
        BEGIN
            IF p_limit IS NULL OR p_limit<1 OR p_limit>101 THEN
                RAISE EXCEPTION 'Adoption page limit must be between 1 and 101'
                    USING ERRCODE='22023';
            END IF;
            v_actor:=NULLIF(current_setting('request_engine.authenticated_principal_id',true),'')::uuid;
            v_revision:=NULLIF(current_setting('request_engine.authority_revision',true),'')::bigint;
            IF v_actor IS NULL OR NOT EXISTS(
                SELECT 1 FROM request_engine.principals p
                JOIN request_engine.principal_authority_grants g ON g.principal_id=p.id
                WHERE p.id=v_actor AND p.principal_plane='platform'
                  AND p.principal_kind='human' AND p.active
                  AND p.authority_revision=v_revision
                  AND g.principal_plane='platform' AND g.authority_plane='platform'
                  AND g.capability_key='platform.organization.read' AND g.status='active'
            ) THEN
                RAISE EXCEPTION 'Current Platform Owner may not inspect adoption requests'
                    USING ERRCODE='42501';
            END IF;
            RETURN QUERY SELECT r.id,r.organization_id,r.controller_principal_id,
                r.source_policy_key,r.target_policy_key,r.expected_authority_revision,
                r.status,r.revision,r.created_at,r.expires_at
              FROM request_engine.controller_policy_adoption_requests r
             WHERE r.status='pending' AND r.expires_at>clock_timestamp()
               AND (p_request_id IS NULL OR r.id=p_request_id)
               AND (p_after IS NULL OR r.id>p_after)
             ORDER BY r.id LIMIT p_limit;
        END $$;
        ALTER FUNCTION request_platform.list_controller_policy_adoptions(uuid,integer,uuid)
            OWNER TO request_platform_definer;
        REVOKE ALL ON FUNCTION request_platform.list_controller_policy_adoptions(
            uuid,integer,uuid)
            FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_platform.list_controller_policy_adoptions(
            uuid,integer,uuid)
            TO request_platform_definer;

        CREATE FUNCTION request_platform.review_controller_policy_adoption(p_request_id uuid)
        RETURNS TABLE(request_id uuid,organization_id uuid,controller_principal_id uuid,
            source_policy_key text,target_policy_key text,expected_authority_revision bigint,
            request_revision bigint,reason text,created_at timestamptz,expires_at timestamptz,
            current_authority_revision bigint,proposed_capabilities text[],
            revoked_capabilities text[])
        LANGUAGE plpgsql STABLE SECURITY DEFINER
        SET search_path=pg_catalog,request_engine,request_platform,pg_temp AS $$
        DECLARE v_actor uuid;
                v_actor_revision bigint;
                v_actor_binding uuid;
                v_request request_engine.controller_policy_adoption_requests%ROWTYPE;
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
            SELECT r.* INTO v_request
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
                RAISE EXCEPTION 'Consenting controller authority has changed'
                    USING ERRCODE='40001';
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

        CREATE FUNCTION request_cmd.read_controller_policy_adoption(
            p_request_id uuid,p_binding_id uuid)
        RETURNS TABLE(request_id uuid,organization_id uuid,controller_principal_id uuid,
            source_policy_key text,target_policy_key text,expected_authority_revision bigint,
            status text,revision bigint,created_at timestamptz,expires_at timestamptz,
            authority_revision_before bigint,authority_revision_after bigint,
            added_capabilities text[])
        LANGUAGE plpgsql STABLE SECURITY DEFINER
        SET search_path=pg_catalog,request_engine,request_cmd,pg_temp AS $$
        DECLARE v_org uuid:=request_engine.current_organization_id();
                v_actor uuid:=NULLIF(current_setting(
                    'request_engine.authenticated_principal_id',true),'')::uuid;
                v_row request_engine.controller_policy_adoption_requests%ROWTYPE;
        BEGIN
            IF v_org IS NULL OR v_actor IS NULL OR p_binding_id IS NULL OR NOT EXISTS(
                SELECT 1 FROM request_engine.organization_root_provisioning_facts f
                JOIN request_engine.principals p ON p.id=f.controller_principal_id
                JOIN request_engine.identity_bindings b ON b.id=f.controller_binding_id
                WHERE f.organization_id=v_org AND f.controller_principal_id=v_actor
                  AND f.controller_binding_id=p_binding_id AND p.principal_plane='tenant'
                  AND p.principal_kind='human' AND p.active AND b.principal_id=v_actor
                  AND b.organization_id=v_org AND b.principal_plane='tenant'
                  AND b.status='active'
            ) THEN
                RAISE EXCEPTION 'Only the active original controller may inspect consent'
                    USING ERRCODE='42501';
            END IF;
            SELECT r.* INTO v_row FROM request_engine.controller_policy_adoption_requests r
             WHERE r.id=p_request_id AND r.organization_id=v_org
               AND r.controller_principal_id=v_actor AND r.controller_binding_id=p_binding_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Adoption request unavailable' USING ERRCODE='P0002';
            END IF;
            RETURN QUERY SELECT v_row.id,v_row.organization_id,v_row.controller_principal_id,
                v_row.source_policy_key,v_row.target_policy_key,v_row.expected_authority_revision,
                CASE WHEN v_row.status='pending' AND v_row.expires_at<=clock_timestamp()
                     THEN 'expired' ELSE v_row.status END,
                v_row.revision,v_row.created_at,v_row.expires_at,f.authority_revision_before,
                f.authority_revision_after,f.added_capabilities
              FROM (SELECT 1) singleton
              LEFT JOIN request_engine.controller_policy_adoption_facts f
                ON f.request_id=v_row.id;
        END $$;
        ALTER FUNCTION request_cmd.read_controller_policy_adoption(uuid,uuid)
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_cmd.read_controller_policy_adoption(uuid,uuid)
            FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_cmd.read_controller_policy_adoption(uuid,uuid)
            TO request_engine_app;
    """)


def downgrade() -> None:
    raise RuntimeError("Controller policy adoption provenance is immutable; use a roll-forward")
