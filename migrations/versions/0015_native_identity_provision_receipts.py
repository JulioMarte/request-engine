"""Atomic native identity provisioning, current authority and immutable replay receipts."""

from alembic import op

revision: str = "0015_native_identity_provision"
down_revision: str | None = "0014_platform_owner_reads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE request_engine.native_identity_provision_receipts (
        actor_principal_id uuid NOT NULL REFERENCES request_engine.principals(id),
        idempotency_key_digest text NOT NULL CHECK(idempotency_key_digest ~ '^[0-9a-f]{64}$'),
        intent_digest text NOT NULL CHECK(intent_digest ~ '^[0-9a-f]{64}$'),
        native_identity_id uuid NOT NULL REFERENCES request_engine.native_identities(id),
        login_handle text NOT NULL CHECK(length(login_handle) BETWEEN 1 AND 320),
        correlation_id uuid,
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        PRIMARY KEY(actor_principal_id, idempotency_key_digest)
    );
    ALTER TABLE request_engine.native_identity_provision_receipts
        OWNER TO request_engine_schema_owner;
    ALTER TABLE request_engine.native_identity_provision_receipts ENABLE ROW LEVEL SECURITY;
    ALTER TABLE request_engine.native_identity_provision_receipts FORCE ROW LEVEL SECURITY;
    CREATE POLICY native_identity_provision_receipts_owner
        ON request_engine.native_identity_provision_receipts TO request_engine_schema_owner
        USING(true) WITH CHECK(true);
    REVOKE ALL ON request_engine.native_identity_provision_receipts FROM PUBLIC,request_engine_app;
    CREATE FUNCTION request_engine.reject_native_identity_provision_receipt_mutation()
    RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog,request_engine,pg_temp AS $$
    BEGIN RAISE EXCEPTION 'provision receipt is immutable' USING ERRCODE='55000'; END $$;
    ALTER FUNCTION request_engine.reject_native_identity_provision_receipt_mutation()
        OWNER TO request_engine_schema_owner;
    REVOKE ALL ON FUNCTION request_engine.reject_native_identity_provision_receipt_mutation()
        FROM PUBLIC;
    CREATE TRIGGER native_identity_provision_receipts_immutable BEFORE UPDATE OR DELETE
        ON request_engine.native_identity_provision_receipts FOR EACH ROW
        EXECUTE FUNCTION request_engine.reject_native_identity_provision_receipt_mutation();

    CREATE FUNCTION request_platform.provision_native_identity(
        p_authority uuid, p_identity uuid, p_login text, p_credential uuid,
        p_verifier text, p_key text, p_intent text
    ) RETURNS TABLE(native_identity_id uuid, login_handle text)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path=pg_catalog,request_engine,pg_temp AS $$
    DECLARE actor_id uuid; actor_revision bigint; retained record; created boolean;
    BEGIN
        PERFORM request_engine.acquire_identity_topology_share();
        IF p_authority IS NULL OR p_identity IS NULL OR p_credential IS NULL
           OR p_login IS NULL OR length(p_login) NOT BETWEEN 1 AND 320
           OR p_key IS NULL OR p_key !~ '^[0-9a-f]{64}$'
           OR p_intent IS NULL OR p_intent !~ '^[0-9a-f]{64}$'
           OR p_verifier IS NULL OR p_verifier NOT LIKE '$argon2id$%' THEN
            RAISE EXCEPTION 'Invalid native provision input' USING ERRCODE='22023';
        END IF;
        BEGIN
            actor_id := NULLIF(current_setting(
                'request_engine.authenticated_principal_id', true),'')::uuid;
            actor_revision := NULLIF(current_setting(
                'request_engine.authority_revision', true),'')::bigint;
        EXCEPTION WHEN invalid_text_representation THEN
            RAISE EXCEPTION 'Malformed platform actor' USING ERRCODE='28000';
        END;
        -- The actor is the shared serialization root of authority withdrawal and
        -- competing administrative retries. Authority is checked before every receipt.
        PERFORM 1 FROM request_engine.principals p WHERE p.id=actor_id
          AND p.principal_plane='platform' AND p.principal_kind='human'
          AND p.active AND p.authority_revision=actor_revision FOR UPDATE;
        IF NOT FOUND OR NOT EXISTS (
            SELECT 1 FROM request_engine.principal_authority_grants g
            WHERE g.principal_id=actor_id AND g.principal_plane='platform'
              AND g.authority_plane='platform' AND g.status='active'
              AND g.capability_key='platform.identity.provision'
        ) THEN
            RAISE EXCEPTION 'Current provision authority required' USING ERRCODE='42501';
        END IF;
        SELECT * INTO retained FROM request_engine.native_identity_provision_receipts r
            WHERE r.actor_principal_id=actor_id AND r.idempotency_key_digest=p_key;
        IF FOUND THEN
            IF retained.intent_digest<>p_intent THEN
                RAISE EXCEPTION 'Conflicting provision intent' USING ERRCODE='23505';
            END IF;
            RETURN QUERY SELECT retained.native_identity_id, retained.login_handle;
            RETURN;
        END IF;
        created := request_auth.create_native_identity(
            p_authority,p_identity,p_login,p_credential,p_verifier);
        IF created IS NULL THEN
            RAISE EXCEPTION 'Native authority unavailable' USING ERRCODE='55000';
        END IF;
        IF NOT created THEN
            RAISE EXCEPTION 'Native login already enrolled' USING ERRCODE='23505';
        END IF;
        INSERT INTO request_engine.native_identity_provision_receipts(
            actor_principal_id,idempotency_key_digest,intent_digest,native_identity_id,
            login_handle,correlation_id)
        VALUES(actor_id,p_key,p_intent,p_identity,p_login,NULLIF(current_setting(
            'request_engine.correlation_id',true),'')::uuid);
        RETURN QUERY SELECT p_identity,p_login;
    END $$;
    ALTER FUNCTION request_platform.provision_native_identity(uuid,uuid,text,uuid,text,text,text)
        OWNER TO request_engine_schema_owner;
    REVOKE ALL ON FUNCTION request_platform.provision_native_identity(
        uuid,uuid,text,uuid,text,text,text) FROM PUBLIC;
    """)


def downgrade() -> None:
    op.execute(
        "DROP FUNCTION request_platform.provision_native_identity("
        "uuid,uuid,text,uuid,text,text,text)"
    )
    op.execute("DROP TABLE request_engine.native_identity_provision_receipts")
    op.execute("DROP FUNCTION request_engine.reject_native_identity_provision_receipt_mutation()")
