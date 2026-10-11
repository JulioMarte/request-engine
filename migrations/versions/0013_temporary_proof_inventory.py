"""Append-only technical retained-version receipts; no destruction worker."""

from alembic import op

revision: str = "0013_temporary_proof_inventory"
down_revision: str | None = "0012_staff_replay_authority"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS(SELECT 1 FROM pg_roles
                WHERE rolname='request_engine_retention_recorder') THEN
                CREATE ROLE request_engine_retention_recorder NOLOGIN NOSUPERUSER
                    NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
            END IF;
        END $$;
        GRANT USAGE ON SCHEMA request_cmd TO request_engine_retention_recorder;
        CREATE TABLE request_engine.temporary_proof_retention_receipts (
            backend_id uuid NOT NULL,
            mount text NOT NULL CHECK(length(mount) BETWEEN 1 AND 64
                AND mount ~ '^[A-Za-z0-9_-]+$'),
            reference text NOT NULL CHECK(reference ~
                '^request-engine/identity-recovery/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/[1-9][0-9]*$'),
            version bigint NOT NULL CHECK(version > 0),
            created_at timestamptz NOT NULL,
            deletion_at timestamptz NOT NULL,
            expires_at timestamptz NOT NULL,
            recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            PRIMARY KEY(backend_id,mount,reference,version,created_at),
            CHECK(length(reference) <= 128),
            CHECK(backend_id <> '00000000-0000-0000-0000-000000000000'::uuid),
            CHECK(created_at < deletion_at AND deletion_at <= expires_at),
            CHECK(isfinite(created_at) AND isfinite(deletion_at) AND isfinite(expires_at))
        );
        ALTER TABLE request_engine.temporary_proof_retention_receipts
            OWNER TO request_engine_schema_owner;
        ALTER TABLE request_engine.temporary_proof_retention_receipts ENABLE ROW LEVEL SECURITY;
        ALTER TABLE request_engine.temporary_proof_retention_receipts FORCE ROW LEVEL SECURITY;
        CREATE POLICY temporary_proof_inventory_owner
            ON request_engine.temporary_proof_retention_receipts TO request_engine_schema_owner
            USING(true) WITH CHECK(true);
        REVOKE ALL ON request_engine.temporary_proof_retention_receipts FROM PUBLIC,
            request_engine_app,request_engine_retention_recorder;
        CREATE FUNCTION request_engine.reject_temporary_proof_receipt_mutation()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog,request_engine,pg_temp AS $$
        BEGIN RAISE EXCEPTION 'retention receipt is immutable' USING ERRCODE='55000'; END;
        $$;
        ALTER FUNCTION request_engine.reject_temporary_proof_receipt_mutation()
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_engine.reject_temporary_proof_receipt_mutation() FROM PUBLIC;
        CREATE TRIGGER temporary_proof_receipts_immutable BEFORE UPDATE OR DELETE
            ON request_engine.temporary_proof_retention_receipts FOR EACH ROW
            EXECUTE FUNCTION request_engine.reject_temporary_proof_receipt_mutation();
        CREATE FUNCTION request_cmd.record_temporary_proof_retention(
            p_backend uuid,p_mount text,p_reference text,p_version bigint,
            p_created timestamptz,p_deletion timestamptz,p_expiry timestamptz)
        RETURNS void LANGUAGE plpgsql SECURITY DEFINER
        SET search_path=pg_catalog,request_engine,pg_temp AS $$
        DECLARE retained request_engine.temporary_proof_retention_receipts;
        BEGIN
            INSERT INTO request_engine.temporary_proof_retention_receipts
                (backend_id,mount,reference,version,created_at,deletion_at,expires_at)
                VALUES(p_backend,p_mount,p_reference,p_version,p_created,p_deletion,p_expiry)
                ON CONFLICT DO NOTHING;
            SELECT * INTO STRICT retained FROM request_engine.temporary_proof_retention_receipts
                WHERE backend_id=p_backend AND mount=p_mount AND reference=p_reference
                  AND version=p_version AND created_at=p_created;
            IF (retained.deletion_at,retained.expires_at)
                IS DISTINCT FROM (p_deletion,p_expiry) THEN
                RAISE EXCEPTION 'retention receipt conflicts' USING ERRCODE='23505';
            END IF;
        END;
        $$;
        ALTER FUNCTION request_cmd.record_temporary_proof_retention(
            uuid,text,text,bigint,timestamptz,timestamptz,timestamptz)
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_cmd.record_temporary_proof_retention(
            uuid,text,text,bigint,timestamptz,timestamptz,timestamptz)
            FROM PUBLIC,request_engine_app;
        GRANT EXECUTE ON FUNCTION request_cmd.record_temporary_proof_retention(
            uuid,text,text,bigint,timestamptz,timestamptz,timestamptz)
            TO request_engine_retention_recorder;
    """)


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
            IF EXISTS(SELECT 1 FROM request_engine.temporary_proof_retention_receipts) THEN
                RAISE EXCEPTION 'retention evidence must be preserved' USING ERRCODE='55000';
            END IF;
        END $$;
        DROP FUNCTION request_cmd.record_temporary_proof_retention(
            uuid,text,text,bigint,timestamptz,timestamptz,timestamptz);
        DROP TABLE request_engine.temporary_proof_retention_receipts;
        DROP FUNCTION request_engine.reject_temporary_proof_receipt_mutation();
        REVOKE USAGE ON SCHEMA request_cmd FROM request_engine_retention_recorder;
    """)
