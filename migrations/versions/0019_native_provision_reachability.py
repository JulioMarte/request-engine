"""Revalidate native authentication posture before provisioning or replay."""

from alembic import op

revision: str = "0019_native_provision_reachable"
down_revision: str | None = "0018_request_definition_admin"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("""
    CREATE FUNCTION request_auth.lock_accepted_native_credential(
        p_credential uuid,p_expected_authority uuid)
    RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER
    SET search_path=pg_catalog,request_engine,pg_temp AS $$
    DECLARE identity_id uuid; authority_id uuid;
    BEGIN
        SELECT c.native_identity_id INTO identity_id FROM (
            SELECT id,native_identity_id FROM request_engine.native_credentials
            WHERE id=p_credential AND kind='password'
            UNION ALL
            SELECT id,native_identity_id FROM request_engine.webauthn_credentials
            WHERE id=p_credential
        ) c;
        IF identity_id IS NULL THEN RETURN NULL; END IF;
        SELECT i.identity_authority_id INTO authority_id
            FROM request_engine.native_identities i WHERE i.id=identity_id;
        IF authority_id IS DISTINCT FROM p_expected_authority THEN RETURN NULL; END IF;
        PERFORM 1 FROM request_engine.identity_authorities a
            WHERE a.id=authority_id AND a.kind='native' AND a.status='active' FOR SHARE;
        IF NOT FOUND THEN RETURN NULL; END IF;
        PERFORM 1 FROM request_engine.native_identities i
            WHERE i.id=identity_id AND i.status='active' FOR SHARE;
        IF NOT FOUND THEN RETURN NULL; END IF;
        -- Credential mutation/recovery follows authority -> identity -> credential.
        PERFORM 1 FROM request_engine.native_credentials c
            WHERE c.id=p_credential AND c.native_identity_id=identity_id
              AND c.kind='password' AND c.status='active' FOR SHARE;
        IF NOT FOUND THEN
            PERFORM 1 FROM request_engine.webauthn_credentials c
                WHERE c.id=p_credential AND c.native_identity_id=identity_id
                  AND c.status='active' FOR SHARE;
            IF NOT FOUND THEN RETURN NULL; END IF;
        END IF;
        IF EXISTS(SELECT 1 FROM request_engine.native_identity_recovery_state r
            WHERE r.native_identity_id=identity_id AND r.state='recovery_restricted') THEN
            RETURN NULL;
        END IF;
        RETURN identity_id;
    END $$;
    ALTER FUNCTION request_auth.lock_accepted_native_credential(uuid,uuid)
        OWNER TO request_engine_schema_owner;
    REVOKE ALL ON FUNCTION request_auth.lock_accepted_native_credential(uuid,uuid) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION request_auth.lock_accepted_native_credential(uuid,uuid)
        TO request_platform_control_definer;

    -- Preserve the existing atomic command body/ACL and add a fail-closed guard
    -- immediately before its receipt lookup. No baseline or applied SQL is rewritten.
    DO $migration$
    DECLARE definition text; marker text; guard text;
    BEGIN
        marker := '        SELECT * INTO retained FROM request_engine.'
                  'native_identity_provision_receipts r';
        guard := $guard$
        IF coalesce(current_setting('request_engine.authentication_method',true),'')
            <>'native_session'
           OR NOT EXISTS (
            SELECT 1 FROM request_engine.identity_bindings b
            WHERE b.principal_id=actor_id AND b.principal_plane='platform'
              AND b.status='active' AND b.subject_id=
                request_auth.lock_accepted_native_credential(NULLIF(current_setting(
                    'request_engine.credential_id',true),'')::uuid,
                    b.identity_authority_id)::text
        ) THEN
            RAISE EXCEPTION 'Current accepted native actor required' USING ERRCODE='42501';
        END IF;
$guard$;
        definition := pg_get_functiondef(
            'request_platform.provision_native_identity(uuid,uuid,text,uuid,text,text,text)'
            ::regprocedure);
        IF position(marker IN definition)=0 THEN
            RAISE EXCEPTION 'Provision guard migration anchor missing';
        END IF;
        EXECUTE replace(definition,marker,guard || marker);
    END $migration$;
    """)


def downgrade() -> None:
    raise NotImplementedError("Authentication authority hardening requires roll-forward")
