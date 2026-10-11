"""Fenced technical cleanup work, never automatic deployment admission."""

from alembic import op

revision: str = "0024_temporary_proof_cleanup"
down_revision: str | None = "0023_native_receipt_columns"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("""
        DO $$ DECLARE worker record; BEGIN
            IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname LIKE 'request_proof_cleanup_%'
                AND rolname<>'request_proof_cleanup_worker') THEN
                RAISE EXCEPTION 'cleanup namespace contains unaudited roles'
                    USING ERRCODE='42501';
            END IF;
            IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='request_proof_cleanup_worker') THEN
                CREATE ROLE request_proof_cleanup_worker NOLOGIN NOSUPERUSER NOCREATEDB
                    NOCREATEROLE NOREPLICATION NOBYPASSRLS;
            END IF;
            SELECT * INTO STRICT worker FROM pg_roles WHERE rolname='request_proof_cleanup_worker';
            IF worker.rolcanlogin OR worker.rolsuper OR worker.rolcreatedb OR worker.rolcreaterole
                OR worker.rolreplication OR worker.rolbypassrls OR worker.rolconfig IS NOT NULL
                OR EXISTS(SELECT 1 FROM pg_auth_members WHERE member=worker.oid)
                OR EXISTS(SELECT 1 FROM pg_db_role_setting WHERE setrole=worker.oid)
                OR EXISTS(SELECT 1 FROM pg_shdepend WHERE refclassid='pg_authid'::regclass
                    AND refobjid=worker.oid AND (deptype='o' OR (deptype='a'
                        AND (dbid=0 OR dbid=(SELECT oid FROM pg_database
                            WHERE datname=current_database()))))) THEN
                RAISE EXCEPTION 'retention worker group is not isolated' USING ERRCODE='42501';
            END IF;
            IF EXISTS(SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member
                WHERE m.roleid=worker.oid AND (m.admin_option OR NOT r.rolcanlogin OR r.rolsuper
                    OR r.rolcreatedb OR r.rolcreaterole OR r.rolreplication OR r.rolbypassrls
                    OR r.rolconfig IS NOT NULL
                    OR EXISTS(SELECT 1 FROM pg_auth_members extra WHERE extra.member=r.oid
                        AND (extra.roleid<>worker.oid OR extra.admin_option)))) THEN
                RAISE EXCEPTION 'retention worker membership is not isolated' USING ERRCODE='42501';
            END IF;
        END $$;
        CREATE TABLE request_engine.temporary_proof_cleanup_work (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            backend_id uuid NOT NULL,
            mount text NOT NULL,
            reference text NOT NULL,
            version bigint NOT NULL,
            created_at timestamptz NOT NULL,
            lease_token uuid,
            lease_until timestamptz,
            attempts integer NOT NULL DEFAULT 0 CHECK(attempts>=0),
            next_attempt_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            terminal boolean NOT NULL DEFAULT false,
            UNIQUE(backend_id,mount,reference,version,created_at),
            FOREIGN KEY(backend_id,mount,reference,version,created_at)
                REFERENCES request_engine.temporary_proof_retention_receipts,
            CHECK((lease_token IS NULL)=(lease_until IS NULL)),
            CHECK(lease_until IS NULL OR isfinite(lease_until)),
            CHECK(isfinite(next_attempt_at))
        );
        CREATE INDEX temporary_cleanup_due ON request_engine.temporary_proof_cleanup_work
            (backend_id,mount,next_attempt_at,id) WHERE NOT terminal;
        CREATE TABLE request_engine.temporary_proof_cleanup_results (
            work_id uuid NOT NULL REFERENCES request_engine.temporary_proof_cleanup_work,
            lease_token uuid NOT NULL,
            attempt integer NOT NULL CHECK(attempt>0),
            outcome text NOT NULL CHECK(outcome IN
                ('destroyed','absent','unverified','denied','unresolved','retained')),
            admission_id uuid NOT NULL CHECK(admission_id<>'00000000-0000-0000-0000-000000000000'),
            admission_digest text NOT NULL CHECK(admission_digest ~ '^[0-9a-f]{64}$'),
            observed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            PRIMARY KEY(work_id,lease_token),
            UNIQUE(work_id,attempt)
        );
        ALTER TABLE request_engine.temporary_proof_cleanup_work
            OWNER TO request_engine_schema_owner;
        ALTER TABLE request_engine.temporary_proof_cleanup_results
            OWNER TO request_engine_schema_owner;
        ALTER TABLE request_engine.temporary_proof_cleanup_work ENABLE ROW LEVEL SECURITY;
        ALTER TABLE request_engine.temporary_proof_cleanup_work FORCE ROW LEVEL SECURITY;
        ALTER TABLE request_engine.temporary_proof_cleanup_results ENABLE ROW LEVEL SECURITY;
        ALTER TABLE request_engine.temporary_proof_cleanup_results FORCE ROW LEVEL SECURITY;
        CREATE POLICY temporary_cleanup_work_owner ON request_engine.temporary_proof_cleanup_work
            TO request_engine_schema_owner USING(true) WITH CHECK(true);
        CREATE POLICY temporary_cleanup_results_owner
            ON request_engine.temporary_proof_cleanup_results
            TO request_engine_schema_owner USING(true) WITH CHECK(true);
        CREATE TRIGGER temporary_cleanup_results_immutable BEFORE UPDATE OR DELETE
            ON request_engine.temporary_proof_cleanup_results FOR EACH ROW
            EXECUTE FUNCTION request_engine.reject_temporary_proof_receipt_mutation();
        REVOKE ALL ON request_engine.temporary_proof_cleanup_work,
            request_engine.temporary_proof_cleanup_results FROM PUBLIC,request_engine_app,
            request_engine_worker,request_retention_recorder,request_proof_cleanup_worker;
        CREATE FUNCTION request_engine.assert_temporary_proof_worker() RETURNS void
        LANGUAGE plpgsql SET search_path=pg_catalog,request_engine,pg_temp AS $$
        DECLARE caller record; worker record; BEGIN
            SELECT * INTO STRICT caller FROM pg_roles WHERE rolname=session_user;
            SELECT * INTO STRICT worker FROM pg_roles WHERE rolname='request_proof_cleanup_worker';
            IF NOT caller.rolcanlogin OR caller.rolsuper OR caller.rolbypassrls
                OR caller.rolcreatedb
                OR caller.rolcreaterole OR caller.rolreplication OR caller.rolconfig IS NOT NULL
                OR NOT pg_has_role(session_user,worker.oid,'MEMBER')
                OR worker.rolcanlogin OR worker.rolsuper OR worker.rolbypassrls
                OR worker.rolcreatedb
                OR worker.rolcreaterole OR worker.rolreplication OR worker.rolconfig IS NOT NULL
                OR EXISTS(SELECT 1 FROM pg_auth_members WHERE member=worker.oid)
                OR EXISTS(SELECT 1 FROM pg_auth_members WHERE member=caller.oid
                    AND (roleid<>worker.oid OR admin_option))
                OR EXISTS(SELECT 1 FROM pg_db_role_setting
                    WHERE setrole IN(caller.oid,worker.oid)) THEN
                RAISE EXCEPTION 'retention worker login is not isolated' USING ERRCODE='42501';
            END IF;
        END $$;
        ALTER FUNCTION request_engine.assert_temporary_proof_worker()
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_engine.assert_temporary_proof_worker() FROM PUBLIC;
        CREATE FUNCTION request_cmd.claim_temporary_proof_cleanup(
            p_backend uuid,p_mount text,p_grace_seconds integer,p_lease_seconds integer)
        RETURNS TABLE(work_id uuid,lease_token uuid,lease_until timestamptz,attempt integer,
            reference text,version bigint,created_at timestamptz,deletion_at timestamptz,
            expires_at timestamptz,admitted_at timestamptz)
        LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,request_engine,pg_temp AS $$
        DECLARE instant timestamptz:=clock_timestamp(); chosen uuid; BEGIN
            PERFORM request_engine.assert_temporary_proof_worker();
            IF p_backend IS NULL OR p_backend='00000000-0000-0000-0000-000000000000'
                OR p_mount IS NULL OR p_mount !~ '^[A-Za-z0-9_-]{1,64}$'
                OR p_grace_seconds IS NULL OR p_grace_seconds NOT BETWEEN 1 AND 604800
                OR p_lease_seconds IS NULL OR p_lease_seconds NOT BETWEEN 10 AND 3600 THEN
                RAISE EXCEPTION 'invalid cleanup claim input' USING ERRCODE='22023';
            END IF;
            INSERT INTO request_engine.temporary_proof_cleanup_work
                (backend_id,mount,reference,version,created_at,next_attempt_at)
            SELECT r.backend_id,r.mount,r.reference,r.version,r.created_at,instant
            FROM request_engine.temporary_proof_retention_receipts r
            WHERE r.backend_id=p_backend AND r.mount=p_mount
              AND r.expires_at+make_interval(secs=>p_grace_seconds)<=instant
              AND NOT EXISTS(SELECT 1 FROM request_engine.temporary_proof_cleanup_work w
                WHERE (w.backend_id,w.mount,w.reference,w.version,w.created_at)=
                    (r.backend_id,r.mount,r.reference,r.version,r.created_at))
            ORDER BY r.expires_at,r.created_at,r.reference,r.version LIMIT 100
            ON CONFLICT DO NOTHING;
            SELECT w.id INTO chosen FROM request_engine.temporary_proof_cleanup_work w
            JOIN request_engine.temporary_proof_retention_receipts r
              USING(backend_id,mount,reference,version,created_at)
            WHERE w.backend_id=p_backend AND w.mount=p_mount AND NOT w.terminal
              AND w.next_attempt_at<=instant AND (w.lease_until IS NULL OR w.lease_until<=instant)
              AND r.expires_at+make_interval(secs=>p_grace_seconds)<=instant
            ORDER BY w.next_attempt_at,w.id FOR UPDATE OF w SKIP LOCKED LIMIT 1;
            IF chosen IS NULL THEN RETURN; END IF;
            UPDATE request_engine.temporary_proof_cleanup_work w
            SET lease_token=gen_random_uuid(),
                lease_until=instant+make_interval(secs=>p_lease_seconds),
                attempts=w.attempts+1 WHERE w.id=chosen;
            RETURN QUERY SELECT w.id,w.lease_token,w.lease_until,w.attempts,
                r.reference,r.version,r.created_at,r.deletion_at,r.expires_at,instant
            FROM request_engine.temporary_proof_cleanup_work w
            JOIN request_engine.temporary_proof_retention_receipts r
              USING(backend_id,mount,reference,version,created_at) WHERE w.id=chosen;
        END $$;
        CREATE FUNCTION request_cmd.finish_temporary_proof_cleanup(
            p_work uuid,p_lease uuid,p_outcome text,p_admission uuid,p_digest text,
            p_retry_seconds integer) RETURNS boolean
        LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,request_engine,pg_temp AS $$
        DECLARE work request_engine.temporary_proof_cleanup_work; BEGIN
            PERFORM request_engine.assert_temporary_proof_worker();
            IF p_work IS NULL OR p_lease IS NULL OR p_outcome IS NULL OR p_outcome NOT IN
                ('destroyed','absent','unverified','denied','unresolved','retained')
                OR p_admission IS NULL OR p_admission='00000000-0000-0000-0000-000000000000'
                OR p_digest IS NULL OR p_digest !~ '^[0-9a-f]{64}$'
                OR p_retry_seconds IS NULL OR p_retry_seconds NOT BETWEEN 1 AND 86400 THEN
                RAISE EXCEPTION 'invalid cleanup result input' USING ERRCODE='22023';
            END IF;
            SELECT * INTO work FROM request_engine.temporary_proof_cleanup_work
                WHERE id=p_work FOR UPDATE;
            IF work.id IS NULL OR work.terminal OR work.lease_token IS DISTINCT FROM p_lease
                OR work.lease_until<=clock_timestamp() THEN RETURN false; END IF;
            INSERT INTO request_engine.temporary_proof_cleanup_results
                (work_id,lease_token,attempt,outcome,admission_id,admission_digest)
            VALUES(work.id,p_lease,work.attempts,p_outcome,p_admission,p_digest);
            UPDATE request_engine.temporary_proof_cleanup_work SET
                terminal=p_outcome IN('destroyed','absent','unverified','denied'),
                lease_token=NULL,lease_until=NULL,
                next_attempt_at=clock_timestamp()+make_interval(secs=>p_retry_seconds)
            WHERE id=p_work;
            RETURN true;
        END $$;
        ALTER FUNCTION request_cmd.claim_temporary_proof_cleanup(uuid,text,integer,integer)
            OWNER TO request_engine_schema_owner;
        ALTER FUNCTION request_cmd.finish_temporary_proof_cleanup(uuid,uuid,text,uuid,text,integer)
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_cmd.claim_temporary_proof_cleanup(uuid,text,integer,integer),
            request_cmd.finish_temporary_proof_cleanup(uuid,uuid,text,uuid,text,integer)
            FROM PUBLIC;
        GRANT USAGE ON SCHEMA request_cmd TO request_proof_cleanup_worker;
        GRANT EXECUTE ON FUNCTION
            request_cmd.claim_temporary_proof_cleanup(uuid,text,integer,integer),
            request_cmd.finish_temporary_proof_cleanup(uuid,uuid,text,uuid,text,integer)
            TO request_proof_cleanup_worker;
    """)


def downgrade() -> None:
    raise RuntimeError(
        "stop cleanup worker and use a reviewed roll-forward; preserve retention facts"
    )
