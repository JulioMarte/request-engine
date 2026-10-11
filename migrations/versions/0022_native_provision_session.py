"""Revalidate the real native session provenance before provisioning receipts."""

from alembic import op

revision: str = "0022_native_provision_session"
down_revision: str | None = "0021_tenant_controller_v6"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("""
    CREATE FUNCTION request_auth.lock_accepted_native_session(
        p_session uuid,p_expected_authority uuid)
    RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER
    SET search_path=pg_catalog,request_engine,pg_temp AS $$
    DECLARE snapshot request_engine.native_sessions%ROWTYPE;
            identity_id uuid; current_epoch bigint;
    BEGIN
        -- Read immutable provenance first; retain canonical authenticator lock order.
        SELECT * INTO snapshot FROM request_engine.native_sessions WHERE id=p_session;
        IF NOT FOUND THEN RETURN NULL; END IF;
        identity_id := request_auth.lock_accepted_native_credential(
            coalesce(snapshot.password_credential_id,snapshot.webauthn_credential_id),
            p_expected_authority);
        IF identity_id IS NULL OR identity_id<>snapshot.native_identity_id THEN
            RETURN NULL;
        END IF;
        SELECT session_epoch INTO current_epoch FROM request_engine.native_identities
            WHERE id=identity_id;
        -- Logout locks only this row; global revocation holds identity before session.
        SELECT * INTO snapshot FROM request_engine.native_sessions
            WHERE id=p_session FOR SHARE;
        IF NOT FOUND OR snapshot.status<>'active'
            OR snapshot.expires_at<=clock_timestamp()
            OR snapshot.session_epoch<>current_epoch OR snapshot.recovery_derived
            OR snapshot.authentication_assurance='recovery'
            OR 'recovery_code'=ANY(snapshot.authentication_methods)
            OR (snapshot.password_credential_id IS NOT NULL
                AND NOT ('password'=ANY(snapshot.authentication_methods)))
            OR (snapshot.webauthn_credential_id IS NOT NULL
                AND NOT ('webauthn'=ANY(snapshot.authentication_methods))) THEN
            RETURN NULL;
        END IF;
        RETURN identity_id;
    END $$;
    ALTER FUNCTION request_auth.lock_accepted_native_session(uuid,uuid)
        OWNER TO request_engine_schema_owner;
    REVOKE ALL ON FUNCTION request_auth.lock_accepted_native_session(uuid,uuid) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION request_auth.lock_accepted_native_session(uuid,uuid)
        TO request_platform_control_definer;

    DO $migration$
    DECLARE definition text; marker text;
    BEGIN
        definition := pg_get_functiondef(
            'request_platform.provision_native_identity(uuid,uuid,text,uuid,text,text,text)'
            ::regprocedure);
        marker := 'request_auth.lock_accepted_native_credential(';
        IF (length(definition)-length(replace(definition,marker,'')))/length(marker)<>1 THEN
            RAISE EXCEPTION 'Provision session migration anchor missing or ambiguous';
        END IF;
        EXECUTE replace(definition,marker,'request_auth.lock_accepted_native_session(');
    END $migration$;
    """)


def downgrade() -> None:
    raise NotImplementedError("Native session authority hardening requires roll-forward")
