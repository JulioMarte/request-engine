"""Rotate native agent credentials without replacing identity or authority."""

from alembic import op

revision: str = "0025_agent_credential_rotation"
down_revision: str | None = "0024_temporary_proof_cleanup"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("""
        CREATE FUNCTION request_cmd.lock_agent_credential_manager(p_target uuid)
        RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER
        SET search_path TO pg_catalog, request_engine, pg_temp AS $$
        DECLARE
            v_org uuid := request_engine.current_organization_id();
            v_actor uuid := NULLIF(current_setting(
                'request_engine.authenticated_principal_id', true), '')::uuid;
            v_identity uuid;
            v_status text;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
            PERFORM 1 FROM request_engine.principals
             WHERE organization_id=v_org AND id=v_actor AND principal_plane='tenant'
               AND principal_kind='human' AND active FOR SHARE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Current HUMAN manager required' USING ERRCODE='42501';
            END IF;
            -- Membership/grant writers serialize on this Principal. Do not acquire
            -- their row locks after it: a trigger may already wait for this root.
            IF NOT EXISTS(SELECT 1 FROM request_engine.staff_memberships
                WHERE organization_id=v_org AND principal_id=v_actor AND status='active')
               OR NOT EXISTS(SELECT 1 FROM request_engine.principal_authority_grants
                WHERE organization_id=v_org AND principal_id=v_actor AND status='active'
                  AND authority_plane='tenant_control' AND capability_key='agent.manage_authority')
            THEN
                RAISE EXCEPTION 'Current agent manager authority required' USING ERRCODE='42501';
            END IF;
            SELECT workload_identity_id, status INTO v_identity,v_status
              FROM request_engine.agent_profiles
             WHERE organization_id=v_org AND principal_id=p_target FOR SHARE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Agent not found' USING ERRCODE='P0002';
            END IF;
            IF v_status NOT IN ('pending','active','suspended') THEN
                RAISE EXCEPTION 'Revoked agent cannot rotate' USING ERRCODE='55000';
            END IF;
            PERFORM 1 FROM request_engine.principals
             WHERE organization_id=v_org AND id=p_target AND principal_kind='agent'
               AND principal_plane='tenant' FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Agent not found' USING ERRCODE='P0002';
            END IF;
            IF EXISTS(SELECT 1 FROM request_engine.principal_authority_grants target
                WHERE target.organization_id=v_org AND target.principal_id=p_target
                  AND target.status='active' AND (target.authority_plane<>'operational'
                  OR target.delegable OR NOT EXISTS(
                    SELECT 1 FROM request_engine.principal_authority_grants manager
                     WHERE manager.organization_id=v_org AND manager.principal_id=v_actor
                       AND manager.capability_key=target.capability_key
                       AND manager.authority_plane='operational' AND manager.status='active'
                       AND manager.delegable))) THEN
                RAISE EXCEPTION 'Agent exceeds current manager ceiling' USING ERRCODE='42501';
            END IF;
            PERFORM 1 FROM request_engine.workload_identities wi
              JOIN request_engine.identity_bindings b
                ON b.identity_authority_id=wi.identity_authority_id AND b.subject_id=wi.id::text
              JOIN request_engine.identity_authorities authority
                ON authority.id=wi.identity_authority_id
             WHERE wi.id=v_identity AND wi.workload_kind='agent' AND wi.status='active'
               AND b.organization_id=v_org AND b.principal_id=p_target
               AND b.status IN ('pending','active','suspended')
               AND authority.kind='workload' AND authority.status='active'
             FOR UPDATE OF wi FOR SHARE OF b,authority;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Agent identity is not usable' USING ERRCODE='55000';
            END IF;
            RETURN v_identity;
        END $$;
        ALTER FUNCTION request_cmd.lock_agent_credential_manager(uuid)
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_cmd.lock_agent_credential_manager(uuid) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_cmd.lock_agent_credential_manager(uuid)
            TO request_engine_app;

        CREATE FUNCTION request_cmd.rotate_agent_credential(
            p_target uuid, p_expected bigint, p_credential uuid, p_digest bytea,
            p_fingerprint text, p_expiry timestamptz)
        RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER
        SET search_path TO pg_catalog, request_engine, pg_temp AS $$
        DECLARE v_identity uuid; v_revision bigint;
        BEGIN
            v_identity := request_cmd.lock_agent_credential_manager(p_target);
            IF p_expected IS NULL OR p_expected<1 OR p_credential IS NULL OR p_digest IS NULL
               OR octet_length(p_digest)<>32 OR p_fingerprint IS NULL
               OR p_fingerprint !~ '^[0-9a-f]{16}$' OR p_expiry IS NULL
               OR p_expiry<=clock_timestamp() THEN
                RAISE EXCEPTION 'Invalid rotation input' USING ERRCODE='22023';
            END IF;
            SELECT authority_revision INTO v_revision FROM request_engine.principals
             WHERE organization_id=request_engine.current_organization_id() AND id=p_target;
            IF v_revision<>p_expected THEN
                RAISE EXCEPTION 'Agent authority revision is stale' USING ERRCODE='40001';
            END IF;
            UPDATE request_engine.workload_credentials SET status='revoked',
                revision=revision+1, revoked_at=clock_timestamp()
             WHERE workload_identity_id=v_identity AND status='active';
            INSERT INTO request_engine.workload_credentials
                (id,workload_identity_id,token_digest,token_fingerprint,expires_at)
             VALUES(p_credential,v_identity,p_digest,p_fingerprint,p_expiry);
            UPDATE request_engine.principals SET authority_revision=authority_revision+1
             WHERE organization_id=request_engine.current_organization_id() AND id=p_target
             RETURNING authority_revision INTO v_revision;
            RETURN v_revision;
        END $$;
        ALTER FUNCTION request_cmd.rotate_agent_credential(uuid,bigint,uuid,bytea,text,timestamptz)
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_cmd.rotate_agent_credential(
            uuid,bigint,uuid,bytea,text,timestamptz)
            FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_cmd.rotate_agent_credential(
            uuid,bigint,uuid,bytea,text,timestamptz)
            TO request_engine_app;

        CREATE FUNCTION request_read.agent_credential_metadata(p_target uuid)
        RETURNS TABLE(credential_id uuid,status text,revision bigint,expires_at timestamptz)
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path TO pg_catalog, request_engine, pg_temp AS $$
            SELECT c.id,c.status,c.revision,c.expires_at
              FROM request_engine.agent_profiles profile
              JOIN request_engine.workload_credentials c
                ON c.workload_identity_id=profile.workload_identity_id
             WHERE profile.organization_id=request_engine.current_organization_id()
               AND profile.principal_id=p_target AND c.status='active'
               AND EXISTS(SELECT 1 FROM request_engine.principals caller
                    JOIN request_engine.principal_authority_grants g
                      ON g.organization_id=caller.organization_id AND g.principal_id=caller.id
                     AND g.status='active' AND g.authority_plane='tenant_control'
                     AND g.capability_key='agent.read'
                    WHERE caller.organization_id=request_engine.current_organization_id()
                      AND caller.id=NULLIF(current_setting(
                        'request_engine.authenticated_principal_id',true),'')::uuid
                      AND caller.principal_kind='human' AND caller.active)
             ORDER BY c.id
        $$;
        ALTER FUNCTION request_read.agent_credential_metadata(uuid)
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_read.agent_credential_metadata(uuid) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_read.agent_credential_metadata(uuid)
            TO request_engine_app;
    """)


def downgrade() -> None:
    op.execute("""
        DROP FUNCTION request_read.agent_credential_metadata(uuid);
        DROP FUNCTION request_cmd.rotate_agent_credential(uuid,bigint,uuid,bytea,text,timestamptz);
        DROP FUNCTION request_cmd.lock_agent_credential_manager(uuid);
    """)
